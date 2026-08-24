"""Unified link parsing plugin: WeChat articles, Coolapk and Tieba posts.

One entry point detects every supported link (group -1, ahead of the agent
and keyword handlers), shows the typing action, parses with a per-URL cache
and re-sends the content: WeChat as a rich message with inline images, the
social platforms as a media group (or formatted text). Per-chat gating uses
the existing ``parse_wechat_enabled`` / ``parse_sites_enabled`` configs.
"""

from __future__ import annotations

import asyncio
import html as html_mod
import io
import re
from typing import Any

import httpx
import pyrogram
from pyrogram import filters
from pyrogram.client import Client
from pyrogram.client import Client as PyrogramClient
from pyrogram.enums import ChatType, ParseMode
from pyrogram.raw.functions.messages.send_message import (
    SendMessage as _RawSendMessage,
)
from pyrogram.raw.functions.messages.upload_media import (
    UploadMedia as _RawUploadMedia,
)
from pyrogram.raw.types.input_media_uploaded_photo import (
    InputMediaUploadedPhoto as _RawInputMediaUploadedPhoto,
)
from pyrogram.raw.types.input_photo import InputPhoto as _RawInputPhoto
from pyrogram.raw.types.input_rich_message import (
    InputRichMessage as _RawInputRichMessage,
)
from pyrogram.types import Message

from kmua import database, i18n
from kmua.common.download import download_capped
from kmua.logger import logger
from kmua.services import link_parse
from kmua.services import wechat as wechat_service

_MAX_IMAGES = 5
_MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
_DOWNLOAD_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_RICH_DOWNLOAD_TIMEOUT = httpx.Timeout(60.0, connect=10.0)

_COMBINED_RE = re.compile(
    r"(?:"
    + link_parse.SOCIAL_URL_RE.pattern
    + r"|"
    + wechat_service.WECHAT_URL_RE.pattern
    + r")"
)

_SOURCE_LABELS = {
    "coolapk": "酷安",
    "tieba": "贴吧",
}


@Client.on_message(filters.regex(_COMBINED_RE), group=-1)
async def parse_social_link(client: Client, message: Message):
    chat = message.chat
    if chat is None or chat.id is None:
        return
    user = message.from_user or message.sender_chat
    if not user or not user.id:
        return
    if not message.text or not message.matches:
        return
    url = message.matches[0].group()
    if not url:
        return
    if not url.startswith("http"):
        url = "https://" + url

    is_wechat = wechat_service.is_wechat_url(url)
    source = ""
    clean_url = ""
    if chat.type in (ChatType.SUPERGROUP, ChatType.GROUP):
        chat_config = await database.get_chat_config(chat.id)
        lang = chat_config.lang
    else:
        chat_config = None
        user_config = await database.get_user_config(user.id)
        lang = user_config.lang
    if is_wechat:
        if chat_config is not None and (
            not chat_config.parse_links_enabled
            or not chat_config.parse_sites_enabled.get(
                "wechat", chat_config.parse_wechat_enabled
            )
        ):
            return
    else:
        matched = link_parse.match_social_url(url)
        if matched is None:
            return
        source, clean_url = matched
        if chat_config is not None and (
            not chat_config.parse_links_enabled
            or not chat_config.parse_sites_enabled.get(source, True)
        ):
            return

    # Chat actions are decorative: a slow/hung send must never stall the
    # whole parse, so bound it and continue on failure.
    try:
        await asyncio.wait_for(
            message.reply_chat_action(pyrogram.enums.ChatAction.TYPING), timeout=8
        )
    except Exception:
        pass

    if is_wechat:
        await _send_wechat_article(client, message, url, lang)
        return
    await _send_social_post(client, message, source, clean_url, lang)


async def _send_wechat_article(
    client: PyrogramClient,
    message: Message,
    article_url: str,
    lang: str,
) -> None:
    """Fetch a WeChat article and re-send it as a rich message.

    Images are uploaded first and referenced as InputPhoto ids inside the
    rich blocks (the native MTProto equivalent of Bot API 10.2 media
    support). Falls back to a media group, then a rich text-only message.
    """
    try:
        article = await wechat_service.fetch_article(article_url)
    except Exception as e:
        logger.error(
            f"link_parse: wechat fetch failed for {article_url}: "
            f"{e.__class__.__name__}: {e}"
        )
        return
    if not article.title and not article.paragraphs:
        return
    chat = message.chat
    assert chat is not None and chat.id is not None
    chat_id = chat.id
    try:
        photo_ids = await _upload_rich_photos(client, chat_id, article)
        await _send_rich_reply(
            client,
            chat_id,
            wechat_service.build_rich_blocks(article, lang, photo_ids),
            photo_ids,
            message.id,
        )
    except Exception as e:
        logger.warning(
            f"link_parse: wechat rich send failed for {article.url}: "
            f"{e.__class__.__name__}: {e}"
        )
        try:
            if article.images:
                await _send_wechat_media_group(client, message, article, lang)
            else:
                raise
        except Exception as e2:
            logger.error(
                f"link_parse: wechat send failed: {e2.__class__.__name__}: {e2}"
            )


async def _send_social_post(
    client: Client,
    message: Message,
    source: str,
    url: str,
    lang: str,
) -> None:
    """Fetch a Coolapk/Tieba post and re-send it as a media group or text."""
    chat = message.chat
    assert chat is not None and chat.id is not None
    post = await link_parse.fetch_social_post(url)
    if post is None:
        return
    if not post.text and not post.images and post.video_url is None:
        return

    caption = _build_caption(post, lang)
    images = await _download_images(post.images)
    try:
        if images:
            await asyncio.wait_for(
                client.send_media_group(
                    chat.id,
                    [
                        pyrogram.types.InputMediaPhoto(
                            media=io.BytesIO(data),
                            caption=caption if i == 0 else "",
                            parse_mode=ParseMode.HTML,
                        )
                        for i, data in enumerate(images)
                    ],
                    reply_parameters=pyrogram.types.ReplyParameters(
                        message_id=message.id
                    ),
                    show_caption_above_media=True,
                ),
                timeout=30,
            )
        else:
            await asyncio.wait_for(
                message.reply_text(
                    caption,
                    parse_mode=ParseMode.HTML,
                    link_preview_options=pyrogram.types.LinkPreviewOptions(
                        is_disabled=False,
                        url=post.url,
                        prefer_large_media=True,
                    ),
                ),
                timeout=30,
            )
    except Exception as e:
        logger.warning(
            f"link_parse: send failed for {post.url}: {e.__class__.__name__}: {e}"
        )
        try:
            await asyncio.wait_for(
                message.reply_text(
                    caption,
                    parse_mode=ParseMode.HTML,
                    link_preview_options=pyrogram.types.LinkPreviewOptions(
                        is_disabled=False,
                        url=post.url,
                        prefer_large_media=True,
                    ),
                ),
                timeout=30,
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# WeChat rich-message sending helpers


async def _send_rich_reply(
    client: PyrogramClient,
    chat_id: int,
    blocks: list[Any],
    photos: list[Any],
    reply_to_message_id: int,
) -> None:
    """Send one rich message replying to the source message.

    Uses raw ``messages.SendMessage`` directly instead of
    ``client.send_rich_message``: that helper's response parsing is broken in
    kurigram 2.2.24 (it indexes ``peer.chat_id`` on an ``InputPeerChannel``,
    raising AttributeError for any group/channel send). Invoking the raw
    function and ignoring the response avoids the bug entirely. ``blocks`` is
    a raw PageBlock list and ``photos`` the InputPhoto list they reference.
    """
    peer = await client.resolve_peer(chat_id)
    assert peer is not None
    await client.invoke(
        _RawSendMessage(
            peer=peer,
            message="",
            random_id=client.rnd_id(),
            reply_to=await pyrogram.utils.get_reply_to(  # type: ignore
                client,
                pyrogram.types.ReplyParameters(message_id=reply_to_message_id),
                None,
                None,
            ),
            rich_message=_RawInputRichMessage(
                blocks=blocks,
                photos=[p for p in photos if p is not None] or None,
            ),
        ),
    )


async def _upload_rich_photos(
    client: PyrogramClient,
    chat_id: int,
    article: wechat_service.WechatArticle,
) -> list[Any]:
    """Upload the article's images, returning InputPhoto objects in
    image-block order (None where a photo failed to download/validate/upload,
    so the rich builder drops that image).
    """
    image_urls = [block.content for block in article.blocks if block.kind == "image"]
    if not image_urls:
        return []
    peer = await client.resolve_peer(chat_id)
    assert peer is not None
    photos: list[Any] = []
    async with httpx.AsyncClient(timeout=_RICH_DOWNLOAD_TIMEOUT) as http_client:
        for idx, image_url in enumerate(image_urls):
            try:
                data = await wechat_service.download_image(http_client, image_url)
                uploaded = await client.save_file(io.BytesIO(data))
                assert uploaded is not None
                media = await client.invoke(
                    _RawUploadMedia(
                        peer=peer,
                        media=_RawInputMediaUploadedPhoto(file=uploaded),
                    )
                )
                photo = getattr(media, "photo", None)
                if photo is None or not getattr(photo, "id", None):
                    raise ValueError("upload returned no photo")
                photos.append(
                    _RawInputPhoto(
                        id=photo.id,
                        access_hash=photo.access_hash,
                        file_reference=photo.file_reference,
                    )
                )
            except Exception as e:
                logger.warning(
                    f"link_parse: wechat rich photo {idx} upload failed for "
                    f"{article.url}: {e.__class__.__name__}: {e}"
                )
                photos.append(None)
    return photos


async def _send_wechat_media_group(
    client: PyrogramClient,
    message: Message,
    article: wechat_service.WechatArticle,
    lang: str,
) -> bool:
    """Download up to 10 images and send them as a media group.

    The caption (title/author/excerpt/link) is shown above the media using
    show_caption_above_media. Failed downloads are skipped; the rest still go
    out. Returns True when the group was sent; on total failure a rich text
    fallback is sent and False is returned.
    """
    caption = wechat_service.build_media_caption(article, lang)
    chat = message.chat
    assert chat is not None and chat.id is not None
    inputs: list[
        pyrogram.types.InputMediaPhoto
        | pyrogram.types.InputMediaVideo
        | pyrogram.types.InputMediaAudio
        | pyrogram.types.InputMediaDocument
    ] = []
    async with httpx.AsyncClient(timeout=_RICH_DOWNLOAD_TIMEOUT) as http_client:
        for idx, image_url in enumerate(article.images[:10]):
            try:
                data = await wechat_service.download_image(http_client, image_url)
            except Exception as e:
                logger.warning(
                    f"link_parse: wechat image {idx} download failed for "
                    f"{article.url}: {e.__class__.__name__}: {e}"
                )
                continue
            inputs.append(
                pyrogram.types.InputMediaPhoto(
                    media=io.BytesIO(data),
                    caption=caption if idx == 0 else "",
                    parse_mode=ParseMode.HTML,
                )
            )
    if not inputs:
        # All downloads failed: fall back to a rich text message.
        await _send_rich_reply(
            client,
            chat.id,
            wechat_service.build_rich_blocks(article, lang),
            [],
            message.id,
        )
        return False
    try:
        await client.send_media_group(
            chat.id,
            inputs,
            reply_parameters=pyrogram.types.ReplyParameters(message_id=message.id),
            # Telegram's caption-above-media layout for the media group.
            show_caption_above_media=True,
        )
        return True
    except Exception as e:
        # Telegram rejected the media group (e.g. PhotoInvalidDimensions):
        # still deliver the article as a rich text message.
        logger.warning(
            f"link_parse: wechat media group rejected for {article.url}: "
            f"{e.__class__.__name__}: {e}"
        )
        await _send_rich_reply(
            client,
            chat.id,
            wechat_service.build_rich_blocks(article, lang),
            [],
            message.id,
        )
        return False


# ---------------------------------------------------------------------------
# Social post sending helpers


async def _download_images(urls: list[str]) -> list[bytes]:
    """Download up to _MAX_IMAGES images; failed downloads are skipped."""
    results: list[bytes] = []
    async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT) as http_client:
        for url in urls[:_MAX_IMAGES]:
            try:
                data = await download_capped(
                    http_client, url, _MAX_DOWNLOAD_BYTES, timeout=_DOWNLOAD_TIMEOUT
                )
                results.append(data)
            except Exception:
                continue
    return results


def _build_caption(post: link_parse.SocialPost, lang: str) -> str:
    lines: list[str] = []
    source_label = _SOURCE_LABELS.get(post.source, post.source)
    lines.append(f"<b>[{html_mod.escape(source_label)}]</b>")
    if post.title:
        lines.append(f"<b>{html_mod.escape(post.title)}</b>")
    if post.text:
        lines.append(
            f"<blockquote expandable=true>{html_mod.escape(link_parse.truncate(post.text, 500))}</blockquote>"
        )
    if post.video_url:
        lines.append(f'🎬 <a href="{html_mod.escape(post.video_url)}">视频</a>')
    lines.append(
        f'🔗 <a href="{html_mod.escape(post.url)}">{html_mod.escape(i18n.t("bot.msg.link_parse.view_original", locale=lang))}</a>'
    )
    return link_parse.truncate("\n".join(lines), 1024)


__all__ = ["parse_social_link"]
