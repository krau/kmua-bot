from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import ContextTypes

from kmua import common
from kmua.logger import logger

_help_text = """
<blockquote expandable="true">
/start - 开始使用|打开菜单
/help - 显示此帮助信息
/config - 更改 bot 在群组中的设置 (开关某些功能)
/waifu - 今天的群友老婆!
/waifu_graph - 老婆关系图!
/q - 记录语录
/d - 删除语录|管理群语录
/qrand - 随机语录
/setqp - 设置随机主动发送语录的概率
/t - 获取头衔|互赠头衔
/sett - 更改 /t 命令所赋予的权限
/setu - 来点色图 (/ω＼*)
/search - 搜索群消息
/import_history - 导入历史消息
/index_stats - 查看索引统计
/set_greet - 设置群组欢迎语
/id - 获取聊天ID
/ip - 查询IP/域名信息
/sr - 超分图片
/reset_contents - 重置对话内容
/set_bot_admin - 在群组中设置bot管理员 (对于bot该用户将具有同等于群主的权限, 慎用)
</blockquote>
↑ 点击展开详细命令说明

对其他人使用 "/"命令 即可对其施法
使用反斜杠可攻受互换
用 "rua" 之类的命令时要用 "//" 或 "/$"

私聊可详细管理个人数据 (使用 /start 开始)

Inline 模式可以查询语录
"""


_help_markup = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("Detail help", url=common.DETAIL_HELP_URL),
            InlineKeyboardButton("Open source", url=common.OPEN_SOURCE_URL),
        ]
    ]
)


async def help(update: Update, _: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )

    message = update.effective_message
    await message.reply_html(
        text=_help_text,
        reply_markup=_help_markup,
    )
