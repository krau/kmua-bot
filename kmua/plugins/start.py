from pyrogram import Client, filters
from pyrogram.enums import ChatType
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from kmua import consts, database
from kmua.logger import logger

_start_bot_markup = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("开源仓库", url=consts.REPO_URL),
            InlineKeyboardButton("详细帮助", url=consts.DOCS_URL),
        ],
        [
            InlineKeyboardButton("个人信息", callback_data="user_data_manage"),
            InlineKeyboardButton("语录管理", callback_data="user_quote_manage"),
        ],
        [
            InlineKeyboardButton("老婆管理", callback_data="user_waifu_manage"),
            InlineKeyboardButton("喵喵喵喵", callback_data="noop"),
        ],
    ]
)


@Client.on_message(filters.command("start"), group=0)
async def start(client: Client, message: Message):
    if message.chat.type != ChatType.PRIVATE:
        if client.me.username not in message.text:
            return
    db_bot_user = await database.get_user_by_id(client.me.id)
    if not db_bot_user:
        db_bot_user = await database.upsert_user(await client.get_me())
    await message.reply(text="Nya~", reply_markup=_start_bot_markup)
