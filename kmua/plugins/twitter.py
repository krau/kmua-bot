"""Native Twitter/X parsing via the FxEmbed API.

Detects twitter.com/x.com status links and delivers the tweet as a rich
message: author, full text, quoted tweet, and media (photos/videos/gifs) as a
media group when present. Runs at group -1 so it wins over the keyword-reply
and agent handlers at group 0; those exclude twitter links explicitly.
"""

import io

import httpx
import pyrogram
from pyrogram.client import Client as PyrogramClient

from kmua import common, database, i18n
from kmua.common.download import download_capped
from kmua.logger import logger
from kmua.services import twitter as twitter_service
from kmua.services.twitter import TWITTER_URL_RE

_DOWNLOAD_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
_MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024  # 200MB per media item


@PyrogramClient.on_message(pyrogram.filters.regex(TWITTER_URL_RE.pattern), group=-1)
async def parse_tweet(client: PyrogramClient, message: pyrogram.types.Message):
    chat = message.chat
    user = message.from_user or message.sender_chat
    if not user or not user.id or not chat or not chat.id:
        return
    if chat.type in (pyrogram.enums.ChatType.SUPERGROUP, pyrogram.enums.ChatType.GROUP):
        chat_config = await database.get_chat_config(chat.id)
        # The same link-parsing switch as artwork parsing governs tweets.
        if not chat_config.parse_links_enabled or not chat_config.parse_artwork_enabled:
            return
        # Per-site switch: "twitter" is off for this chat.
        if not chat_config.parse_sites_enabled.get("twitter", True):
            return
        lang = chat_config.lang
    else:
        user_config = await database.get_user_config(user.id)
        lang = user_config.lang
    if not message.matches or not message.text:
        return
    tweet_url = message.matches[0].group()
    if not tweet_url:
        return
    if not tweet_url.startswith("http"):
        tweet_url = "https://" + tweet_url

    await message.reply_chat_action(pyrogram.enums.ChatAction.TYPING)
    tweet = await twitter_service.fetch_tweet(tweet_url)
    if tweet is None:
        return
    if not tweet.text and not tweet.media:
        return

    try:
        if tweet.media:
            await _send_tweet_media(client, message, tweet, lang)
        else:
            await message.reply_text(
                twitter_service.build_tweet_text(tweet, lang),
                parse_mode=pyrogram.enums.ParseMode.HTML,
                link_preview_options=pyrogram.types.LinkPreviewOptions(
                    is_disabled=False,
                    url=tweet.url,
                    prefer_large_media=True,
                ),
            )
    except Exception as e:
        logger.error(f"twitter: send failed: {e.__class__.__name__}: {e}")


async def _send_tweet_media(
    client: PyrogramClient,
    message: pyrogram.types.Message,
    tweet: twitter_service.TweetData,
    lang: str,
) -> None:
    """Download up to 10 media items and send them as a media group with the
    tweet text as caption. Failed downloads are skipped; if nothing downloads
    the tweet falls back to a text message.
    """
    caption = _build_caption(tweet, lang)
    chat = message.chat
    assert chat is not None and chat.id is not None
    inputs: list[
        pyrogram.types.InputMediaPhoto
        | pyrogram.types.InputMediaVideo
        | pyrogram.types.InputMediaAudio
        | pyrogram.types.InputMediaDocument
    ] = []
    async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT) as http_client:
        for idx, media in enumerate(tweet.media[:10]):
            try:
                data = await _download_media(http_client, media)
            except Exception as e:
                logger.warning(
                    f"twitter: media {idx} download failed for {tweet.url}: "
                    f"{e.__class__.__name__}: {e}"
                )
                continue
            upload = data if isinstance(data, str) else io.BytesIO(data)
            if media.kind == "video":
                inputs.append(
                    pyrogram.types.InputMediaVideo(
                        media=upload,
                        caption=caption if idx == 0 else "",
                        parse_mode=pyrogram.enums.ParseMode.HTML,
                        supports_streaming=True,
                    )
                )
            else:
                inputs.append(
                    pyrogram.types.InputMediaPhoto(
                        media=upload,
                        caption=caption if idx == 0 else "",
                        parse_mode=pyrogram.enums.ParseMode.HTML,
                    )
                )
    if not inputs:
        await message.reply_text(
            twitter_service.build_tweet_text(tweet, lang),
            parse_mode=pyrogram.enums.ParseMode.HTML,
            link_preview_options=pyrogram.types.LinkPreviewOptions(
                is_disabled=False,
                url=tweet.url,
                prefer_large_media=True,
            ),
        )
        return
    await client.send_media_group(
        chat.id,
        inputs,
        reply_parameters=pyrogram.types.ReplyParameters(message_id=message.id),
        show_caption_above_media=True,
    )


async def _download_media(
    client: httpx.AsyncClient, media: twitter_service.TweetMedia
) -> str | bytes:
    """Return a cached file_id (Telegram sends it without a download) or the
    downloaded bytes; raises when the download fails or is oversized."""
    cached = await common.memttlcache.get(f"twitter:media_file_id:{media.url}")
    if cached:
        return cached
    return await download_capped(
        client, media.url, _MAX_DOWNLOAD_BYTES, timeout=_DOWNLOAD_TIMEOUT
    )


def _build_caption(tweet: twitter_service.TweetData, lang: str) -> str:
    """Short caption for the media group: author + text excerpt + link."""
    import html as html_mod

    lines: list[str] = []
    if tweet.author_name:
        handle = f"@{tweet.author_screen_name}" if tweet.author_screen_name else ""
        lines.append(
            f"<b>{html_mod.escape(tweet.author_name)}</b> {html_mod.escape(handle)}".rstrip()
        )
    if tweet.text:
        lines.append(
            f"<blockquote expandable=true>{html_mod.escape(twitter_service.truncate(tweet.text, 300))}</blockquote>"
        )
    lines.append(
        f'🔗 <a href="{html_mod.escape(tweet.url)}">{html_mod.escape(i18n.t("bot.msg.twitter.view_original", locale=lang))}</a>'
    )
    caption = "\n".join(lines)
    return twitter_service.truncate(caption, 1024)


__all__ = ["parse_tweet"]
