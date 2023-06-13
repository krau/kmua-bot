from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ChatAction
from ..utils import message_recorder
from ..logger import logger
import random


async def today_waifu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    await message_recorder(update, context)
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
    is_had_waifu = False
    if not context.bot_data["today_waifu"].get(user_id, None):
        context.bot_data["today_waifu"][user_id] = {}
    waifu_id = context.bot_data["today_waifu"][user_id].get(chat_id, None)
    if not waifu_id:
        group_member: list[int] = list(context.chat_data["members_data"].keys())
        group_member.remove(user_id)
        if not group_member:
            await update.message.reply_text(text="你现在没有老婆, 因为kmua的记录中找不到其他群友")
            return
        waifu = await context.bot.get_chat_member(
            chat_id=chat_id, user_id=random.choice(group_member)
        )
    else:
        waifu = await context.bot.get_chat_member(
            chat_id=chat_id,
            user_id=waifu_id,
        )
        is_had_waifu = True
    waifu = waifu.user
    avatar = await waifu.get_profile_photos(limit=1)
    if is_had_waifu:
        text = f"你今天已经抽过老婆了\! {waifu.mention_markdown_v2()} 是你今天的老婆\!"
    else:
        text = f"你今天的群友老婆是 {waifu.mention_markdown_v2()} \!"
    if avatar.photos:
        avatar = avatar.photos[0][0].file_id
        await update.message.reply_photo(
            photo=avatar,
            caption=text,
            parse_mode="MarkdownV2",
        )
    else:
        await update.message.reply_markdown_v2(text=text)
    context.bot_data["today_waifu"][user_id][chat_id] = waifu.id
    logger.info(f"Bot: {text}")
