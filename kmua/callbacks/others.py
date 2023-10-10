from telegram import Update
from telegram.ext import ContextTypes

from kmua.logger import logger
from kmua.config import settings
import kmua.dao as dao


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


async def error_notice_control(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in settings.owners:
        return
    is_enabled = context.bot_data.get("error_notice", False)
    text = "已关闭" if is_enabled else "已开启"
    text += "错误通知"
    context.bot_data["error_notice"] = not is_enabled
    await update.message.reply_text(text)
