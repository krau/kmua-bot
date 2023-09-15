from telegram import (
    Update,
)
from telegram.ext import ContextTypes
from .chatdata import chat_data_manage


async def manage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == chat.GROUP or chat.type == chat.SUPERGROUP:
        await chat_data_manage(update, context)
        return
