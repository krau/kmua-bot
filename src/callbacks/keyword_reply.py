import random

from telegram import (
    Update,
)
from telegram.ext import ContextTypes
from telegram.constants import ChatAction
from zhconv import convert
from ..logger import logger
from ..data import word_dict
from ..utils import message_recorder


async def keyword_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    message_text = update.effective_message.text.replace(
        context.bot.username, ""
    ).lower()
    message_text = convert(message_text, "zh-cn")
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=ChatAction.TYPING
    )
    for keyword, resplist in word_dict.items():
        if keyword in message_text:
            sent_message = await update.effective_message.reply_text(
                random.choice(resplist), quote=True
            )
            logger.info(f"Bot: {sent_message.text}")
            break
    await message_recorder(update, context)
