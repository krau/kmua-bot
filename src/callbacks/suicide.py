from telegram import Update
from telegram.ext import ContextTypes

from ..logger import logger
from ..utils import message_recorder, random_unit
from ..data import suicide_fail_msg
import random


async def suicide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    await message_recorder(update, context)
    if random_unit(0.01):
        await update.effective_message.reply_text(text="成功注销地球OL账号!")
        return
    text = f"紫砂失败! 因为{random.choice(suicide_fail_msg)}!"
    await update.effective_message.reply_text(text=text)