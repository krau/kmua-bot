from pyrogram import Client, types
from kmua.logger import logger


async def help(cilent: Client, message: types.Message):
    user = message.sender_chat or message.from_user
    logger.info(f"[{message.chat.title}]({user.id})" + f" {message.text}")
    help_text = """
这是使用 Pyrogram 重写的 kmua, 摸鱼开发中
    
命令:
/help - 帮助
/id - 获取ID
"""
    reply_markup = types.InlineKeyboardMarkup(
        [
            [
                types.InlineKeyboardButton(
                    "Detail help", url="https://krau.github.io/kmua-bot/"
                ),
                types.InlineKeyboardButton(
                    "Open source", url="https://github.com/krau/kmua-bot/tree/pyro"
                ),
            ]
        ]
    )
    await message.reply_text(help_text, reply_markup=reply_markup)
