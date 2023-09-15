from telegram import (
    Update,
)
from telegram.ext import ContextTypes
from ..common.chat import get_chat_info
from ..common.user import verify_user_can_manage_bot
from ..logger import logger


async def chat_data_manage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    logger.info(f"chat_data_manage: {chat.title}")
    text = get_chat_info(chat)
    await chat.send_message(text=text)
