from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ..logger import logger
from ..utils import message_recorder


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    await message_recorder(update, context)
    if update.effective_chat.type != "private":
        if update.effective_message.text == "/start":
            # 如果是群聊，且没有艾特，直接返回
            return
        await _start_in_group(update, context)
        return
    start_bot_markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "拉我进群", url=f"https://t.me/{context.bot.username}?startgroup=new"
                ),
                InlineKeyboardButton("开源主页", url="https://github.com/krau/kmua-bot"),
                InlineKeyboardButton("详细帮助", url="https://krau.github.io/kmua-bot/"),
            ],
            [
                InlineKeyboardButton("你的数据", callback_data="user_data_manage"),
                InlineKeyboardButton("名言管理", callback_data="user_quote_manage"),
            ],
        ]
    )
    if update.callback_query:
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=update.callback_query.message.id,
            text="喵喵喵喵喵?",
            reply_markup=start_bot_markup,
        )
        return
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="喵喵喵喵喵?",
        reply_markup=start_bot_markup,
    )


async def _start_in_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    start_bot_markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "私聊咱", url=f"https://t.me/{context.bot.username}?start=start"
                )
            ]
        ]
    )
    sent_message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="喵喵喵?",
        reply_markup=start_bot_markup,
    )
    logger.info(f"Bot:{sent_message.text}")
    await context.bot.send_sticker(
        chat_id=update.effective_chat.id,
        sticker="CAACAgEAAxkBAAIKWGREi3q4O_H40T66DbTZGyNAf0CbAALPAAN92oBFKGj8op00zJ8vBA",
    )
