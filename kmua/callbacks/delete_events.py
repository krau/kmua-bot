from telegram import Update
from telegram.ext import ContextTypes

from kmua import common, dao
from kmua.logger import logger


async def switch_delete_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    开关删除事件消息功能

    :param update: Update
    :param context: Context
    """
    user = update.effective_user
    chat = update.effective_chat
    message = update.effective_message
    logger.info(f"[{chat.title}]({user.name}) {message.text}")
    if not await common.verify_user_can_manage_bot_in_chat(user, chat, update, context):
        return
    delete_events_enabled = dao.get_chat_delete_events_enabled(chat)
    dao.update_chat_delete_events_enabled(chat, not delete_events_enabled)
    await message.reply_text(
        f"Delete events enabled: {not delete_events_enabled}",
        quote=True,
    )


async def delete_event_message(update: Update, _: ContextTypes.DEFAULT_TYPE):
    """
    删除事件消息

    :param update: Update
    :param _: Context
    """
    chat = update.effective_chat
    if not dao.get_chat_delete_events_enabled(chat):
        return
    logger.info(f"[{chat.title}] delete event message")
    if update.message:
        try:
            await update.message.delete()
        except Exception as e:
            msg = f"delete event message failed: {e.__class__.__name__}:{e}"
            logger.warning(msg)
            await update.message.reply_text(
                msg + "\n请检查是否赋予 bot 删除消息权限, 或使用 /switch_delete_events 关闭该功能",
                quote=True,
            )
