from telegram import (
    Update,
)
from telegram.ext import ContextTypes

import kmua.common as common
from kmua.logger import logger
import kmua.dao as dao


async def chat_data_manage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    logger.info(f"chat_data_manage: {chat.title}")
    message = update.effective_message
    text = common.get_chat_info(chat)
    await message.reply_text(text=text)
    # TODO: manage chat data


async def chat_title_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    logger.info(f"update_chat_title: {chat.title}")
    title = chat.title
    dao.update_chat_title(chat=chat, title=title)
