import io
import random
import re

import httpx
from PIL import Image
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update
from telegram.constants import ChatAction, ChatType, ParseMode
from telegram.error import TimedOut
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown

from kmua import config, dao
from kmua.common.utils import escape_html
from kmua.config import settings
from kmua.logger import logger

_manyacg_api_url: str = settings.get("manyacg_api", "https://api.manyacg.top/v1")
_manyacg_api_url = _manyacg_api_url.removesuffix("/") if _manyacg_api_url else None
_manyacg_api_key = settings.get("manyacg_api_key")

if _manyacg_api_url:
    httpx_client = httpx.AsyncClient(
        base_url=_manyacg_api_url,
        timeout=30,
    )

_MANYACG_CHANNEL = config.settings.get("manyacg_channel", "moreacg")
_MANYACG_BOT = config.settings.get("manyacg_bot", "kirakabot")

_nsfwjs_api: str = settings.get("nsfwjs_api")
_nsfwjs_api = _nsfwjs_api.removesuffix("/") if _nsfwjs_api else None
_nsfwjs_api_token = settings.get("nsfwjs_token")


async def setu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    logger.info(
        f"[{chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    if update.effective_message.reply_to_message:
        if update.effective_message.reply_to_message.photo and _nsfwjs_api:
            await _classify_setu(update, context)
            return
    if not _manyacg_api_url:
        await update.effective_message.reply_text(text="咱才没有涩图呢", quote=True)
        return

    if (
        chat.type in (chat.GROUP, chat.SUPERGROUP)
        and not dao.get_chat_config(chat).setu_enabled
    ):
        await update.effective_message.reply_text(text="这里不允许涩图哦", quote=True)
        return

    if context.user_data.get("setu_cd", False):
        await update.effective_message.reply_text(text="太快了, 不行!", quote=True)
        return
    context.user_data["setu_cd"] = True

    try:
        resp = await httpx_client.post(
            url="/artwork/random",
        )
    except Exception as e:
        logger.error(f"setu error: {e.__class__.__name__}:{e}")
        await update.effective_message.reply_text(text="失败惹，请稍后再试", quote=True)
        return
    try:
        if resp.status_code >= 400:
            raise Exception(f"status_code: {resp.status_code}")
        artwork: dict = resp.json()["data"][0]
        picture: dict = artwork["pictures"][
            random.randint(0, len(artwork["pictures"]) - 1)
        ]
        detail_link = f"https://t.me/{_MANYACG_CHANNEL}/{picture['message_id']}"
        sent_message = await update.effective_message.reply_photo(
            photo=picture["regular"],
            caption=f"这是你要的涩图\n[{escape_markdown(artwork['title'], 2)}]({artwork['source_url']})\n",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "详情",
                            url=detail_link,
                        ),
                        InlineKeyboardButton(
                            "原图",
                            url=f"https://t.me/{_MANYACG_BOT}/?start=file_{picture['id']}",
                        ),
                    ]
                ]
            ),
            has_spoiler=resp.json()["data"][0]["r18"],
            quote=True,
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        logger.info(f"Bot: {sent_message.caption}")
    except TimedOut:
        pass
    except Exception as e:
        logger.error(f"setu error: {e.__class__.__name__}:{e}")
        await update.effective_message.reply_text(text="失败惹，请稍后再试", quote=True)
    finally:
        context.user_data["setu_cd"] = False


async def _classify_setu(update: Update, _: ContextTypes.DEFAULT_TYPE):
    target_message = update.effective_message.reply_to_message
    if not target_message.photo or not _nsfwjs_api:
        return
    try:
        async with httpx.AsyncClient() as client:
            sent_message = await target_message.reply_text(
                text="少女看涩图中...", quote=True
            )
            file = await target_message.photo[-1].get_file()
            file_bytes = bytes(await file.download_as_bytearray())
            resp = await client.post(
                url=f"{_nsfwjs_api}/classify",
                headers={"Authorization": f"Bearer {_nsfwjs_api_token}"},
                data=file_bytes,
                timeout=30,
            )
            if resp.status_code != 200:
                logger.error(f"nsfwjs error: {resp.json()}")
                await sent_message.edit_text(text="失败惹，请稍后再试", quote=True)
                return
            result: dict[str, float] = resp.json()
            await sent_message.delete()
            nsfw_class = max(result, key=result.get)
            for k, v in result.items():
                result[k] = round(v * 100, 2)
            text = ""
            match nsfw_class:
                case "Drawing":
                    text = f"这是1张普通的插画! (大概有 {result[nsfw_class]}% 的可能性吧..."
                    text += f"涩情度: {result['Hentai']}%)"
                case "Hentai":
                    text = f"Hentai...你满脑子都是涩涩的事情嘛? 涩情度: {result[nsfw_class]}%"
                case "Neutral":
                    text = f"这是一张普通的图片! (大概有 {result[nsfw_class]}% 的可能性吧...)"
                case "Porn":
                    text = (
                        f"这是一张大人才能看的图片(Porn)! 涩情度: {result[nsfw_class]}%"
                    )
                case "Sexy":
                    text = f"这是一张比较涩的图片... (大概有 {result[nsfw_class]}% 的可能性吧...)"
            sent_message = await target_message.reply_text(text=text, quote=True)
            logger.info(f"Bot: {sent_message.text}")
    except Exception as e:
        logger.error(f"nsfwjs error: {e.__class__.__name__}:{e}")
        await update.effective_message.reply_text(text="失败惹，请稍后再试", quote=True)


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


async def parse_artwork(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _manyacg_api_key:
        return
    chat = update.effective_chat
    if chat.type in (ChatType.SUPERGROUP, ChatType.GROUP):
        if not dao.get_chat_config(chat).parse_artwork_enabled:
            return
    text = update.effective_message.text
    artwork_url = ""
    for regex in ARTWORK_ALL_REGEX:
        match = regex.search(text)
        if match:
            artwork_url = match.group()
            break
    if not artwork_url:
        return
    logger.info(f"parse_artwork: {artwork_url}")
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_PHOTO
    )
    try:
        resp = await httpx_client.get(
            "/artwork/fetch",
            params={"url": artwork_url},
            headers={"X-API-KEY": _manyacg_api_key},
            timeout=60,
        )
    except Exception as e:
        logger.error(f"parse_artwork error: {e.__class__.__name__}:{e}")
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
    try:
        media = []
        caption = f"<a href='{artwork_source_url}'>{escape_html(artwork_title)}</a>\n<blockquote expandable=true>{escape_html(artwork_description)}</blockquote>"
        if artwork_pictures_count > 10:
            caption += f"\n这个作品有{artwork_pictures_count}张图片哦"
        async with httpx.AsyncClient() as client:
            for picture in artwork_pictures:
                pic_bytes: bytes = (await client.get(picture["original"])).content
                if (
                    len(pic_bytes) > 1024 * 1024 * 10
                    or picture["width"] + picture["height"] > 10000
                ):
                    image = Image.open(io.BytesIO(pic_bytes))
                    max_size = 2560
                    ratio = max_size / max(image.width, image.height)
                    if ratio < 1:
                        new_size = (int(image.width * ratio), int(image.height * ratio))
                        image = image.resize(new_size, Image.Resampling.LANCZOS)
                    output = io.BytesIO()
                    image.convert("RGB").save(output, format="JPEG", quality=90)
                    pic_bytes = output.getvalue()
                    output.close()
                media.append(
                    InputMediaPhoto(
                        media=pic_bytes,
                        has_spoiler=artwork_r18,
                        caption=caption if picture["index"] == 0 else None,
                        parse_mode=ParseMode.HTML,
                    )
                )
        await update.effective_message.reply_media_group(
            media=media,
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.error(f"parse_artwork error: {e.__class__.__name__}:{e}")
