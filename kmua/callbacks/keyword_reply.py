import asyncio
import random

from telegram import (
    Update,
)
from telegram.constants import ChatAction
from telegram.error import BadRequest
from telegram.ext import ContextTypes
from zhconv import convert

from kmua import common
from kmua.logger import logger

from .friendship import ohayo, oyasumi


async def keyword_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    关键词回复

    :param update: Update
    :param context: Context
    """
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
    all_resplist = []
    for keyword, resplist in common.word_dict.items():
        if keyword in message_text:
            all_resplist.extend(resplist)
            if keyword == "早":
                await ohayo(update, context)
            if keyword == "晚安":
                await oyasumi(update, context)
    if all_resplist:
        sent_message = await update.effective_message.reply_text(
            text=random.choice(all_resplist),
            quote=True,
        )
        logger.info("Bot: " + sent_message.text)
    common.message_recorder(update, context)
    if sent_message:
        await asyncio.sleep(30)
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
