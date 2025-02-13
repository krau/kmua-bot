from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from kmua import common, dao
from kmua.logger import logger


async def unpin_channel_pin(update: Update, _: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    logger.info(f"[{chat.title}({chat.id})({chat.username})]<{user.name}>")
    if not dao.get_chat_unpin_channel_pin_enabled(chat):
        return

    if message.is_automatic_forward:
        try:
            await message.unpin()
        except BadRequest as e:
            logger.warning(f"{e.__class__.__name__}:{e}")


async def switch_unpin_channel_pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        await message.reply_text("你没有权限哦", quote=True)
        return
    unpin_channel_pin_enabled = dao.get_chat_unpin_channel_pin_enabled(chat)
    dao.update_chat_unpin_channel_pin_enabled(chat, not unpin_channel_pin_enabled)
    await message.reply_text(
        f"Unpin channel pin enabled: {not unpin_channel_pin_enabled}",
        quote=True,
    )
