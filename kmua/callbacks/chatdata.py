from telegram import (
    Update,
)
from telegram.ext import ContextTypes

from kmua import common, dao
from kmua.logger import logger


async def chat_data_manage(update: Update, _: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    logger.info(f"chat_data_manage: {chat.title}")
    message = update.effective_message
    text = common.get_chat_info(chat)
    await message.reply_text(text=text)


async def chat_title_update(update: Update, _: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    logger.info(f"update_chat_title: {chat.title}")
    title = chat.title
    dao.update_chat_title(chat=chat, title=title)


async def chat_migration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.trace(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + "<chat_migration>"
    )
    message = update.message
    application = context.application
    application.migrate_chat_data(message=message)
    old_chat_id = message.migrate_from_chat_id
    new_chat_id = message.migrate_to_chat_id
    if old_chat_id is None or new_chat_id is None:
        return
    dao.update_chat_id(old_chat_id, new_chat_id)
