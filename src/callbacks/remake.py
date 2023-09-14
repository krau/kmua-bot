import random

from telegram import Update
from telegram.ext import ContextTypes

from ..data import birthplace, country, role
from ..logger import logger
from ..common.message import message_recorder
from ..common.utils import random_unit


async def remake(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    if random_unit(0.114):
        await update.effective_message.reply_text(text="重开失败!您没能出生!")
        return
    text = f"重开成功\! 您出生在*{random.choice(country)}*的*{random.choice(birthplace)}*\! 是*{random.choice(role)}*\!"  # noqa: E501
    sent_message = await update.effective_message.reply_text(
        text=text, parse_mode="MarkdownV2"
    )
    await message_recorder(update, context)
    logger.info(f"Bot: {sent_message.text}")
