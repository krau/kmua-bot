import random

from telegram import Update
from telegram.ext import ContextTypes

from ..data import suicide_fail_msg
from ..logger import logger
from ..utils import message_recorder, random_unit


async def suicide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    if random_unit(0.01):
        await update.effective_message.reply_text(text="成功注销地球OL账号!")
        return
    text = f"紫砂失败! 因为{random.choice(suicide_fail_msg)}!"
    sent_message = await update.effective_message.reply_text(text=text)
    await message_recorder(update, context)
    logger.info(f"Bot: {sent_message.text}")
