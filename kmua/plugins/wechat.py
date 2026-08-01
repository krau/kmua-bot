"""WeChat article parsing: detect mp.weixin.qq.com links and re-send the
article as a rich Telegram message (media group when the article has images,
formatted text otherwise).

Follows the parse_artwork pattern: a regex filter on group 0, gated per chat
by ChatConfig.parse_wechat_enabled.
"""

import io
from typing import Any

import httpx
import pyrogram
from pyrogram.client import Client as PyrogramClient

# kurigram's raw messages.SendMessage is not re-exported from the package
# namespace, so import it from its module file directly.
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

from kmua import database
from kmua.logger import logger
from kmua.services import wechat as wechat_service
from kmua.services.wechat import WECHAT_URL_RE

_DOWNLOAD_TIMEOUT = httpx.Timeout(60.0, connect=10.0)


# group -1: run before the group-0 handlers (keyword replies, wake_agent),
# which own group 0 and break after the first filter match.
@PyrogramClient.on_message(pyrogram.filters.regex(WECHAT_URL_RE.pattern), group=-1)
async def parse_wechat_article(client: PyrogramClient, message: pyrogram.types.Message):
    chat = message.chat
    user = message.from_user or message.sender_chat
    if not user or not user.id or not chat or not chat.id:
        return
    if chat.type in (pyrogram.enums.ChatType.SUPERGROUP, pyrogram.enums.ChatType.GROUP):
        chat_config = await database.get_chat_config(chat.id)
        if not chat_config.parse_wechat_enabled:
            return
        lang = chat_config.lang
    else:
        user_config = await database.get_user_config(user.id)
        lang = user_config.lang
    assert chat.id is not None
    if not message.matches or not message.text:
        return
    article_url = message.matches[0].group()
    if not article_url:
        return
    if not article_url.startswith("http"):
        article_url = "https://" + article_url
    if not wechat_service.is_wechat_url(article_url):
        return

    await message.reply_chat_action(pyrogram.enums.ChatAction.TYPING)
    try:
        article = await wechat_service.fetch_article(article_url)
    except Exception as e:
        logger.error(
            f"wechat: fetch failed for {article_url}: {e.__class__.__name__}: {e}"
        )
        return
    if not article.title and not article.paragraphs:
        return

    try:
        # One rich message: structured blocks (heading, block-quoted body,
        # images at their original document positions) with the images
        # uploaded first and referenced as InputPhoto ids — the native
        # MTProto equivalent of Bot API 10.2 media support.
        photo_ids = await _upload_rich_photos(client, chat.id, article)
        await _send_rich_reply(
            client,
            chat.id,
            wechat_service.build_rich_blocks(article, lang, photo_ids),
            photo_ids,
            message.id,
        )
    except Exception as e:
        logger.warning(
            f"wechat: rich send failed for {article.url}: {e.__class__.__name__}: {e}"
        )
        try:
            if article.images:
                await _send_media_group(client, message, article, lang)
            else:
                raise
        except Exception as e2:
            logger.error(f"wechat: send failed: {e2.__class__.__name__}: {e2}")


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
    async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT) as http_client:
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
                    f"wechat: rich photo {idx} upload failed for {article.url}: "
                    f"{e.__class__.__name__}: {e}"
                )
                photos.append(None)
    return photos


async def _send_media_group(
    client: PyrogramClient,
    message: pyrogram.types.Message,
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
    async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT) as http_client:
        for idx, image_url in enumerate(article.images[:10]):
            try:
                data = await wechat_service.download_image(http_client, image_url)
            except Exception as e:
                logger.warning(
                    f"wechat: image {idx} download failed for {article.url}: "
                    f"{e.__class__.__name__}: {e}"
                )
                continue
            inputs.append(
                pyrogram.types.InputMediaPhoto(
                    media=io.BytesIO(data),
                    caption=caption if idx == 0 else "",
                    parse_mode=pyrogram.enums.ParseMode.HTML,
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
            f"wechat: media group rejected for {article.url}: "
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


__all__ = ["parse_wechat_article"]
