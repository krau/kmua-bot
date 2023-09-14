import random

from telegram import (
    Update,
)
from telegram.constants import ChatAction
from telegram.ext import ContextTypes
from zhconv import convert
import asyncio
from ..data import word_dict
from ..logger import logger
from ..common.message import message_recorder
from .friendship import ohayo, oyasumi
from telegram.error import BadRequest

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
    sent_message = None
    for keyword, resplist in word_dict.items():
        if keyword in message_text:
            text = random.choice(resplist)
            text = text.replace("name", update.effective_user.name)
            sent_message = await update.effective_message.reply_text(
                text, allow_sending_without_reply=False, quote=True
            )
            logger.info(f"Bot: {sent_message.text}")
            if keyword == "早":
                await ohayo(update, context)
            if keyword == "晚安":
                await oyasumi(update, context)
            break
    await message_recorder(update, context)
    await asyncio.sleep(30)
    if sent_message:
        source_message = sent_message.reply_to_message
        try:
            await source_message.edit_reply_markup()
        except BadRequest as e:
            if e.message == "Message can't be edited":
                pass
            elif e.message == "Message to edit not found":
                await sent_message.delete()
            else:
                logger.error(f"{e.__class__.__name__}: {e}")
