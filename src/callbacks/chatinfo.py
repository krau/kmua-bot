from telegram import (
    Update,
)
from ..logger import logger
from telegram.ext import ContextTypes


async def getid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    if update.effective_message.reply_to_message:
        await _getid_has_reply(update, context)
    else:
        await _getid_no_reply(update, context)


async def _getid_has_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    target_message = message.reply_to_message
    target = (
        target_message.sender_chat
        or target_message.forward_from
        or target_message.forward_from_chat
        or target_message.from_user
    )
    target_id = target.id
    chat_id = update.effective_chat.id
    user = message.sender_chat or message.from_user
    user_id = user.id
    text = f"""
*Chat ID*: `{chat_id}`

你的 ID: `{user_id}`

被回复者 ID: `{target_id}`
"""
    await message.reply_text(text, parse_mode="MarkdownV2")


async def _getid_no_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_message.sender_chat or update.effective_message.from_user
    user_id = user.id
    text = f"""
*Chat ID*: `{chat_id}`
你的 ID: `{user_id}`
"""
    await update.effective_message.reply_text(text, parse_mode="MarkdownV2")
