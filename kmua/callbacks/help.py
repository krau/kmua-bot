from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown

from kmua import common
from kmua.logger import logger


async def help(update: Update, _: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    help_text = """
/start - 开始使用|打开菜单
/help - 显示此帮助信息
/waifu - 今天的群友老婆!
/waifu_graph - 老婆关系图!
/q - 记录语录
/d - 删除语录|管理群语录
/qrand - 随机语录
/setqp - 设置主动发送语录的概率
/t - 获取头衔|互赠头衔
/setu - 来点色图 (/ω＼*) (如无响应就是没启用)
/switch_waifu - 开关老婆功能
/switch_delete_events - 开关删除事件消息的功能 (bot 需要删除消息权限)
/switch_unpin_channel_pin - 开关取消频道消息置顶的功能 (bot 需要置顶权限)
/search - 搜索群消息
/enable_search - 启用搜索功能
/disable_search - 禁用搜索功能
/import_history - 导入历史消息
/index_stats - 查看索引统计
/id - 获取聊天ID
/set_greet - 设置群组欢迎语
/ip - 查询IP/域名信息
/set_bot_admin - 在群组中设置bot管理员 (对于bot该用户将具有同等于群主的权限, 慎用)

对其他人使用 "/"命令 即可对其施法
使用反斜杠可攻受互换
用 "rua" 之类的命令时要用 "//" 或 "/$"

私聊可详细管理个人数据 (使用 /start 开始)

Inline 模式可以查询语录
"""
    help_markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Detail help", url=common.DETAIL_HELP_URL),
                InlineKeyboardButton("Open source", url=common.OPEN_SOURCE_URL),
            ]
        ]
    )
    message = update.effective_message
    await message.reply_markdown_v2(
        text=escape_markdown(help_text, 2),
        reply_markup=help_markup,
    )
