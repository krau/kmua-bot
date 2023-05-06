import random

from telegram import (
    Update,
)
from telegram.ext import ContextTypes

from ..logger import logger
from ..data import weni_data
from ..utils import message_recorder


async def weni(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    await message_recorder(update, context)
    message_text = update.effective_message.text.replace(
        context.bot.username, ""
    ).lower()
    for keyword, resplist in weni_data.items():
        if keyword in message_text:
            await update.effective_message.reply_text(
                random.choice(resplist), quote=True
            )
            return
