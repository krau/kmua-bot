from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import ContextTypes

from ..logger import logger


_back_home_markup = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("返回", callback_data="back_home"),
        ]
    ]
)


async def user_data_manage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    img_quote_len = len(context.bot_data["quotes"].get(user_id, {}).get("img", []))
    text_quote_len = len(context.bot_data["quotes"].get(user_id, {}).get("text", []))
    quote_len = img_quote_len + text_quote_len
    pm_kmua_num = context.user_data.get("pm_kmua_num", 0) + 1
    context.user_data["pm_kmua_num"] = pm_kmua_num
    group_msg_num = context.user_data.get("group_msg_num", 0)
    text_num = context.user_data.get("text_num", 0)
    photo_num = context.user_data.get("photo_num", 0)
    sticker_num = context.user_data.get("sticker_num", 0)
    voice_num = context.user_data.get("voice_num", 0)
    video_num = context.user_data.get("video_num", 0)
    document_num = context.user_data.get("document_num", 0)
    user_data_manage_markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("返回", callback_data="back_home"),
                InlineKeyboardButton("❗清空", callback_data="clear_user_data"),
            ]
        ]
    )
    statistics_data = f"""
你的统计信息:

你的ID: `{update.effective_user.id}`
已保存的名言总数: *{quote_len}*
图片名言数量: *{img_quote_len}*
文字名言数量: *{text_quote_len}*
私聊Kmua次数: *{pm_kmua_num}*
水群消息数: *{group_msg_num}*
总文字消息数: *{text_num}*
总图片消息数: *{photo_num}*
总贴纸消息数: *{sticker_num}*
总语音消息数: *{voice_num}*
总视频消息数: *{video_num}*
总文件消息数: *{document_num}*

点击下方清空按钮将立即删除以下数据:
1 已保存的名言总数
2 图片名言数量
3 文字名言数量
"""
    sent_message = await context.bot.edit_message_text(
        chat_id=update.effective_chat.id,
        text=statistics_data,
        reply_markup=user_data_manage_markup,
        parse_mode="MarkdownV2",
        message_id=update.callback_query.message.id,
    )
    logger.info(f"Bot: {sent_message.text}")


async def clear_user_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.bot_data["quotes"].get(user_id, {}):
        sent_message = await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            text="你还没有名言",
            message_id=update.callback_query.message.id,
            reply_markup=_back_home_markup,
        )
        logger.info(f"Bot: {sent_message.text}")
        return
    context.bot_data["quotes"][user_id] = {}
    await context.bot.edit_message_text(
        chat_id=update.effective_chat.id,
        message_id=update.callback_query.message.message_id,
        text="已清空你的语录",
        reply_markup=_back_home_markup,
    )


async def user_quote_manage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    quotes = context.bot_data["quotes"].get(user_id, {}).get("text", [])
    if not quotes:
        sent_message = await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            text="你还没有名言",
            message_id=update.callback_query.message.id,
            reply_markup=_back_home_markup,
        )
        logger.info(f"Bot: {sent_message.text}")
        return
    quotes_content = [quote.content for quote in quotes]
    keyboard, line = [], []
    for i, quote in enumerate(quotes):
        line.append(InlineKeyboardButton(i + 1, callback_data=str(quote.id)))
        if len(line) == 5:
            keyboard.append(line.copy())
            line.clear()
    if line:
        keyboard.append(line)
    keyboard.append([InlineKeyboardButton("返回", callback_data="back_home")])
    quote_manage_markup = InlineKeyboardMarkup(keyboard)
    text = "你的名言:\n\n"
    for i, quote in enumerate(quotes_content):
        text += f"{i + 1}. {quote}\n"
    sent_message = await context.bot.edit_message_text(
        chat_id=update.effective_chat.id,
        text=text,
        reply_markup=quote_manage_markup,
        message_id=update.callback_query.message.id,
    )
    logger.info(f"Bot: {sent_message.text}")
