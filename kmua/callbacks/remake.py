import random
import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from kmua.logger import logger
import kmua.common as common


_country = [
    "中国",
    "日本",
    "韩国",
    "朝鲜",
    "缅甸",
    "美国",
    "加拿大",
    "英国",
    "法国",
    "德国",
    "阿根廷",
    "印度",
]
_role = ["男孩子", "女孩子", "薯条", "xyn", "猫猫", "狗狗", "鼠鼠"]
_birthplace = ["首都", "省会", "直辖市", "市区", "县城", "自治区", "农村", "大学"]


async def remake(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("remake_cd", False):
        return
    context.user_data["remake_cd"] = True
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    if common.random_unit(0.114):
        sent_message = await update.effective_message.reply_text(text="重开失败!您没能出生!")
    else:
        text = f"重开成功\! 您出生在*{random.choice(_country)}*的*{random.choice(_birthplace)}*\! 是*{random.choice(_role)}*\!"  # noqa: E501
        sent_message = await update.effective_message.reply_text(
            text=text, parse_mode="MarkdownV2"
        )
    common.message_recorder(update, context)
    logger.info(f"Bot: {sent_message.text}")
    await asyncio.sleep(30)
    context.user_data["remake_cd"] = False
