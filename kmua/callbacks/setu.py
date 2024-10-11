import random

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import TimedOut
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown

from kmua import config, dao
from kmua.config import settings
from kmua.logger import logger

_manyacg_api_url: str = settings.get("manyacg_api")
_manyacg_api_url = _manyacg_api_url.removesuffix("/") if _manyacg_api_url else None

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
            url="/api/v1/artwork/random",
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
        detail_link = (
            f"https://t.me/{_MANYACG_CHANNEL}/{picture['message_id']}"
            if picture["message_id"] != 0
            else f"{_manyacg_api_url}/artwork/{artwork['id']}"
        )
        sent_message = await update.effective_message.reply_photo(
            photo=picture["regular"],
            caption=f"这是你要的涩图\n[{escape_markdown(artwork['title'],2)}]({artwork['source_url']})\n",
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
                    text += f"涩情度: {result["Hentai"]}%)"
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
