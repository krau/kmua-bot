from telegram import (
    Update,
)
from telegram.ext import ContextTypes
from ..common.chat import get_chat_info
from ..logger import logger
from ..service import chat as chat_service


async def chat_data_manage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    logger.info(f"chat_data_manage: {chat.title}")
    text = get_chat_info(chat)
    await chat.send_message(text=text)
    # TODO: manage chat data


async def chat_title_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    logger.info(f"update_chat_title: {chat.title}")
    title = chat.title
    chat_service.update_chat_title(chat=chat, title=title)
