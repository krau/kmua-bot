from pyrogram import Client, types
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from kmua.logger import logger
from kmua import common


async def init(client: Client, message: types.Message):
    user = message.sender_chat or message.from_user
    if not common.verify_user_can_manage_bot(user):
        return
    logger.info(f"[{user.username or user.full_name}]")
    await client.set_bot_commands(
        [
            types.BotCommand("help", "帮助"),
            types.BotCommand("id", "获取ID"),
        ]
    )
    await message.reply_text("Bot init success!")


_status_markup = InlineKeyboardMarkup(
    [[InlineKeyboardButton("Refresh", callback_data="status_refresh")]]
)


async def status(client: Client, message: types.Message):
    user = message.sender_chat or message.from_user
    logger.info(f"[{user.username or user.full_name}]")
    await message.reply_text(common.get_bot_status(), reply_markup=_status_markup)


async def status_refresh(client: Client, callback_query: types.CallbackQuery):
    logger.info(
        f"[{callback_query.from_user.username or callback_query.from_user.full_name}]"
    )
    await callback_query.answer(cache_time=2)
    await callback_query.edit_message_text(
        common.get_bot_status(), reply_markup=_status_markup
    )
