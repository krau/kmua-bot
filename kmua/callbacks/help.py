from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import ContextTypes

import kmua.common as common
from kmua.logger import logger


async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    help_text = """
命令:
/start - 开始使用|打开菜单
/help - 显示此帮助信息
/waifu - 今天的群友老婆!
/waifu_graph - 老婆关系图!
/switch_waifu - 开关老婆功能
/q - 记录语录
/d - 删除语录|管理群语录
/qrand - 随机语录
/t - 获取头衔|互赠头衔
/setqp - 设置主动发送语录的概率
/setu - 来点色图 (/ω＼*) (如无响应就是没启用)
/switch_delete_events - 开关删除事件消息的功能 (bot 需要管理员权限)
/id - 获取聊天ID
/set_greet - 设置群组欢迎语
/set_bot_admin - 在群组中设置bot管理员 (对于bot该用户将具有同等于群主的权限, 慎用)

私聊可详细管理个人数据 (使用 /start 开始)

对其他人使用 "/"命令 即可对其施法
使用反斜杠可攻受互换
用 "rua" 之类的命令时要用 "//" 或 "/$"
"""
    help_markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Detail help", url="https://krau.github.io/kmua-bot/"
                ),
                InlineKeyboardButton(
                    "Open source", url="https://github.com/krau/kmua-bot"
                ),
            ]
        ]
    )
    message = update.effective_message
    await message.reply_text(
        text=help_text,
        reply_markup=help_markup,
    )
    common.message_recorder(update, context)
    logger.info("Bot: <help text>")
