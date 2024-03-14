from telegram import (
    Chat,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from kmua import common
from kmua.logger import logger


async def getid(update: Update, _: ContextTypes.DEFAULT_TYPE):
    """
    获取聊天ID
    """
    message = update.effective_message
    user = message.sender_chat or message.from_user
    logger.info(
        f"[{update.effective_chat.title}]({user.title if isinstance(user,Chat) else user.name})"
        + f" {message.text}"
    )
    if target_message := message.reply_to_message:
        target = common.get_message_origin(target_message)
        await message.reply_text(
            text=f"""
*Chat ID*: `{message.chat_id}`
*Your ID*: `{user.id}`
*Target ID*: `{target.id}`
""",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    else:
        await message.reply_text(
            text=f"""
*Chat ID*: `{message.chat_id}`
*Your ID*: `{user.id}`
""",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
