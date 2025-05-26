import html
import io
import re

import httpx
import pyrogram

from kmua import common, database, i18n
from kmua.config import app_config
from kmua.logger import logger

from . import utils

PIXIV_REGEX = re.compile(
    r"pixiv\.net/(?:artworks/|i/|member_illust\.php\?(?:[\w=&]*\&|)illust_id=)(\d+)"
)
TWITTER_REGEX = re.compile(r"(?:twitter|x)\.com/([^/]+)/status/(\d+)")
BILIBILI_REGEX = re.compile(r"t\.bilibili\.com/(\d+)|bilibili\.com/opus/(\d+)")
DANBOORU_REGEX = re.compile(r"danbooru\.donmai\.us/posts/\d+")
KEMONO_REGEX = re.compile(r"kemono\.su/\w+/user/\d+/post/\d+")
YANDERE_REGEX = re.compile(r"yande\.re/post/show/\d+")
NHENTAI_REGEX = re.compile(r"nhentai\.net/g/\d+")
ARTWORK_ALL_REGEX = [
    PIXIV_REGEX,
    TWITTER_REGEX,
    BILIBILI_REGEX,
    DANBOORU_REGEX,
    KEMONO_REGEX,
    YANDERE_REGEX,
    NHENTAI_REGEX,
]

httpx_client = httpx.AsyncClient(
    base_url=app_config.manyacg_api_url, timeout=30, headers={"User-Agent": "KMUA Bot"}
)


@pyrogram.Client.on_message(
    pyrogram.filters.regex("|".join([r.pattern for r in ARTWORK_ALL_REGEX])), group=0
)
async def parse_artwork(client: pyrogram.Client, message: pyrogram.types.Message):
    if not app_config.manyacg_api_key:
        return
    chat = message.chat
    if chat.type in (pyrogram.enums.ChatType.SUPERGROUP, pyrogram.enums.ChatType.GROUP):
        chat_config = await database.get_chat_config(chat.id)
        if not chat_config.parse_artwork_enabled:
            return
        lang = chat_config.lang
    else:
        user_config = await database.get_user_config(message.from_user.id)
        lang = user_config.lang
    if not message.matches:
        return
    artwork_url = message.matches[0].group()
    if not artwork_url:
        return
    await message.reply_chat_action(pyrogram.enums.ChatAction.UPLOAD_PHOTO)
    try:
        resp = await httpx_client.get(
            "/artwork/fetch",
            params={"url": artwork_url},
            headers={"X-API-KEY": app_config.manyacg_api_key},
            follow_redirects=True,
            timeout=60,
        )

    except Exception as e:
        logger.error(f"Error fetching artwork: {e}")
        return
    if resp.status_code != 200:
        return
    artwork: dict = resp.json()
    if artwork["status"] != 200:
        return
    artwork_title = artwork["data"]["title"]
    artwork_description = artwork["data"]["description"]
    artwork_source_url = artwork["data"]["source_url"]
    artwork_r18 = artwork["data"]["r18"]
    artwork_pictures = artwork["data"]["pictures"][:10]
    artwork_pictures_count = len(artwork["data"]["pictures"])
    cache_id = artwork["data"]["cache_id"]
    try:
        media = []
        caption = f"<a href='{artwork_source_url}'>{html.escape(artwork_title)}</a>\n<blockquote expandable=true>{html.escape(artwork_description)}</blockquote>"
        if artwork_pictures_count > 10:
            caption += i18n.t(
                "bot.msg.manyacg.artwork_pictures_count",
                locale=lang,
            ).format(count=artwork_pictures_count)
            if cache_id:
                caption += f" <a href='https://t.me/{app_config.manyacg_bot}/?start=info_{cache_id}'>{i18n.t('bot.msg.manyacg.seefull', locale=lang)}</a>"
        async with httpx.AsyncClient() as client:
            for picture in artwork_pictures:
                photo = await utils.prepare_media(client, picture)
                media.append(
                    pyrogram.types.InputMediaPhoto(
                        media=io.BytesIO(photo) if isinstance(photo, bytes) else photo,
                        has_spoiler=artwork_r18,
                        caption=caption if picture["index"] == 0 else None,
                        parse_mode=pyrogram.enums.ParseMode.HTML,
                    )
                )
        msgs = await message.reply_media_group(media=media)
        for idx, msg in enumerate(msgs):
            image_url = artwork_pictures[idx]["original"]
            photo_file_id = msg.photo.file_id
            await common.memttlcache.set(
                f"artwork:pic_file_id:{image_url}", photo_file_id, ttl=86400
            )
    except Exception as e:
        logger.error(f"parse_artwork error: {e.__class__.__name__}:{e}")
