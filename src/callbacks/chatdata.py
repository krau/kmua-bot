from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import ContextTypes

from ..logger import logger


_clear_chat_data_markup = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("算了", callback_data="cancel_clear_chat_data"),
            InlineKeyboardButton("确认清空", callback_data="clear_chat_data"),
        ]
    ]
)


async def clear_chat_data_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    if update.effective_chat.type != "private":
        this_chat_member = await update.effective_chat.get_member(
            update.effective_user.id
        )
        if this_chat_member.status != "creator":
            await update.effective_message.reply_text("你没有权限哦")
            return
    sent_message = await update.message.reply_text(
        text="确认清空聊天数据吗?\n此操作将清空 bot 所记录在该聊天的*所有数据*",
        reply_markup=_clear_chat_data_markup,
        parse_mode="MarkdownV2",
    )
    logger.info(f"Bot: {sent_message.text}")


async def clear_chat_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        if (
            update.effective_user.id
            != update.callback_query.message.reply_to_message.from_user.id
        ):
            await context.bot.answer_callback_query(
                callback_query_id=update.callback_query.id,
                text="你没有权限哦",
                show_alert=True,
            )
            return
    await update.callback_query.message.edit_text(text="正在清空聊天数据...")
    if update.effective_chat.type == "private":
        context.application.drop_user_data(update.effective_user.id)
    context.application.drop_chat_data(update.effective_chat.id)
    await update.callback_query.message.edit_text(text="聊天数据已清空")


async def clear_chat_data_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        if (
            update.effective_user.id
            != update.callback_query.message.reply_to_message.from_user.id
        ):
            await context.bot.answer_callback_query(
                callback_query_id=update.callback_query.id,
                text="你没有权限哦",
                show_alert=True,
            )
            return
    await update.callback_query.message.delete()
