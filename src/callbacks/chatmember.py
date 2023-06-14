from telegram import Update
from telegram.ext import ContextTypes

from ..logger import logger


async def chat_member_left(update: Update, context: ContextTypes.DEFAULT_TYPE):
    updated_member = update.effective_user
    try:
        del context.chat_data["members_data"][updated_member.id]
        logger.debug(
            f"将 {updated_member.full_name} 退出了群聊 {update.effective_chat.title} "
        )
        logger.debug(
            f"将 {updated_member.full_name} 从 {update.effective_chat.title} 数据中移除"
        )
    except KeyError:
        logger.debug(f"{updated_member.full_name} 未在 {update.effective_chat.title} 数据中")
