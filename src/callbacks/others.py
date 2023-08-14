from telegram import Update
from telegram.ext import ContextTypes

from ..config.config import settings
from ..logger import logger


async def chat_migration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.trace(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + "<chat_migration>"
    )
    message = update.message
    application = context.application
    application.migrate_chat_data(message=message)


async def error_notice_control(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in settings.owners:
        return
    is_enabled = context.bot_data.get("error_notice", False)
    text = "已关闭" if is_enabled else "已开启"
    text += "错误通知"
    context.bot_data["error_notice"] = not is_enabled
    await update.message.reply_text(text)


async def clear_user_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in settings.owners:
        return
    context.bot_data["user_info"] = {}
    await context.application.persistence.flush()
    await update.message.reply_text("已清除用户信息缓存")
