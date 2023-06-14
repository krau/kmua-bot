from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import ContextTypes

from ..logger import logger
from ..utils import message_recorder


async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    await message_recorder(update, context)
    help_text = """
命令:
/help - 显示此帮助信息
/start - 开始使用
/q - 载入史册
/d - 移出史册
/c - 清空史册
/t - 获取头衔|互赠头衔
/setqp - 设置发名言概率
/rank - 群统计信息
/bnhhsh - 不能好好说话!
/waifu - 今天的群友老婆

私聊:
可查询自己的统计信息
可删除自己的名言
可以和 kmua 聊天

互动:
对其他人使用 "/"命令 即可对其施法
例子:
A使用"/透"回复B的消息
Bot: "A透了B!"
使用反斜杠可主客互换

Inline 模式:
在任意聊天框艾特我即可使用,
支持搜索名言, 例如: @kmuav2bot 原神
"""
    help_markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("详细帮助", url="https://krau.github.io/kmua-bot/"),
                InlineKeyboardButton("源码", url="https://github.com/krau/kmua-bot"),
            ]
        ]
    )
    sent_message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=help_text,
        reply_markup=help_markup,
    )
    logger.info(f"Bot: {sent_message.text}")
