from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from ..logger import logger
from ..model import MemberData
from ..utils import message_recorder, sort_topn_bykey


async def group_rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    if update.effective_chat.type == "private":
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="请在群组中使用哦",
        )
        logger.info(f"Bot: {sent_message.text}")
        return
    members_data = context.chat_data.get("members_data", {})
    if len(members_data) < 5:
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="数据不足,请多水水群吧~",
            reply_to_message_id=update.effective_message.message_id,
        )
        logger.info(f"Bot: {sent_message.text}")
        return
    quote_num_top: list[MemberData] = sort_topn_bykey(
        members_data, min(5, len(members_data)), "quote_num"
    )
    quote_num = len(context.chat_data.get("quote_messages", {}))

    quote_top1 = quote_num_top[0]
    quote_top2 = quote_num_top[1]
    quote_top3 = quote_num_top[2]
    quote_top4 = quote_num_top[3]
    quote_top5 = quote_num_top[4]
    text = f"""
截止到 {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}:

本群共有 *{quote_num}* 条名言,

排行榜:
1 [{quote_top1.name}](tg://user?id={quote_top1.id}) : *{quote_top1.quote_num}* 条
2 [{quote_top2.name}](tg://user?id={quote_top2.id}) : *{quote_top2.quote_num}* 条
3 [{quote_top3.name}](tg://user?id={quote_top3.id}) : *{quote_top3.quote_num}* 条
4 [{quote_top4.name}](tg://user?id={quote_top4.id}) : *{quote_top4.quote_num}* 条
5 [{quote_top5.name}](tg://user?id={quote_top5.id}) : *{quote_top5.quote_num}* 条
"""
    sent_message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        parse_mode="Markdown",
    )
    await message_recorder(update, context)
    logger.info(f"Bot: {sent_message.text}")
