import asyncio
import random

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from kmua.config import settings
from kmua.logger import logger

_manyacg_api_url: str = settings.get("manyacg_api")
_manyacg_api_url = _manyacg_api_url.removesuffix("/") if _manyacg_api_url else None
_manyacg_api_token: str = settings.get("manyacg_token")

_MANYACG_CHANNEL = "manyacg"
_MANYACG_BOT = "kirakabot"


async def setu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    if update.effective_message.reply_to_message:
        await _classify_setu(update, context)
        return
    if not _manyacg_api_url:
        await update.effective_message.reply_text(text="咱才没有涩图呢")
        return
    if context.user_data.get("setu_cd", False):
        await update.effective_message.reply_text(text="太快了, 不行!")
        return
    context.user_data["setu_cd"] = True

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url=f"{_manyacg_api_url}/v1/artwork/random",
                headers={"Authorization": f"Bearer {_manyacg_api_token}"},
            )
            if resp.status_code != 200:
                await update.effective_message.reply_text(
                    text="失败惹，请稍后再试", quote=True
                )
                return
            picture: dict = resp.json()["pictures"][
                random.randint(0, len(resp.json()["pictures"]) - 1)
            ]

            sent_message = await update.effective_message.reply_photo(
                photo=picture["thumbnail"],
                caption=resp.json()["title"],
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "Source",
                                url=f"https://t.me/{_MANYACG_CHANNEL}/{picture['telegram_info']['message_id']}",
                            ),
                            InlineKeyboardButton(
                                "Original File",
                                url=f"https://t.me/{_MANYACG_BOT}/?start=file_{picture['telegram_info']['message_id']}",
                            ),
                        ]
                    ]
                ),
                has_spoiler=resp.json()["r18"],
                quote=True,
            )
            logger.info(f"Bot: {sent_message.caption}")
    except Exception as e:
        logger.error(f"setu error: {e.__class__.__name__}:{e}")
        await update.effective_message.reply_text(text="失败惹，请稍后再试", quote=True)
    finally:
        await asyncio.sleep(3)
        context.user_data["setu_cd"] = False


_nsfwjs_api: str = settings.get("nsfwjs_api")
_nsfwjs_api = _nsfwjs_api.removesuffix("/") if _nsfwjs_api else None
_nsfwjs_api_token = settings.get("nsfwjs_token")


async def _classify_setu(update: Update, _: ContextTypes.DEFAULT_TYPE):
    target_message = update.effective_message.reply_to_message
    if not (target_message.photo or target_message.document or _nsfwjs_api):
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
                await sent_message.edit_text(text="失败惹，请稍后再试")
                return
            result: dict[str, float] = resp.json()
            await sent_message.delete()
            nsfw_class = max(result, key=result.get)
            for k, v in result.items():
                result[k] = round(v * 100, 2)
            text = ""
            logger.info(f"nsfwjs: {result}")
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
            await target_message.reply_text(text=text, quote=True)
    except Exception as e:
        logger.error(f"nsfwjs error: {e.__class__.__name__}:{e}")
        await update.effective_message.reply_text(text="失败惹，请稍后再试", quote=True)
