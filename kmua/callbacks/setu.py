import asyncio

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from kmua.config import settings
from kmua.logger import logger

_api_url: str = settings.get("manyacg_api")
_api_url = _api_url.removesuffix("/") if _api_url else None


async def setu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    if not _api_url:
        return

    if context.user_data.get("setu_cd", False):
        await update.effective_message.reply_text(text="太快了, 不行!", quote=True)
        return
    context.user_data["setu_cd"] = True

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url=f"{_api_url}/v1/artwork/random")
            if resp.status_code != 200:
                await update.effective_message.reply_text(
                    text="失败惹，请稍后再试", quote=True
                )
                return
            sent_message = await update.effective_message.reply_photo(
                photo=resp.json()["data"]["pictures"][0]["direct_url"],
                caption=resp.json()["data"]["title"],
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "Source", url=resp.json()["data"]["source_url"]
                            ),
                            InlineKeyboardButton("Channel", url="https://t.me/manyacg"),
                        ]
                    ]
                ),
                has_spoiler=resp.json()["data"]["r18"],
                quote=True,
            )
            logger.info(f"Bot: {sent_message.caption}")
    except Exception as e:
        logger.error(f"setu error: {e.__class__.__name__}:{e}")
        await update.effective_message.reply_text(text="失败惹，请稍后再试", quote=True)
    finally:
        await asyncio.sleep(3)
        context.user_data["setu_cd"] = False
