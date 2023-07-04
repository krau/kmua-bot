import random
import asyncio

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from ..logger import logger
from ..utils import message_recorder


async def today_waifu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    await message_recorder(update, context)
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not context.bot_data["today_waifu"].get(user_id, None):
        context.bot_data["today_waifu"][user_id] = {}
    await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
    is_got_waifu = True
    is_success = False
    waifu_id = context.bot_data["today_waifu"][user_id].get(chat_id, None)
    if not waifu_id:
        is_got_waifu = False
        group_member: list[int] = list(context.chat_data["members_data"].keys())
        to_remove = [
            user_id,
            5304501737,
            1031952739,
            609517172,
            777000,
            136817688,
            1087968824,
            context.bot.id,
        ]
        group_member = [member for member in group_member if member not in to_remove]
        if not group_member:
            await update.message.reply_text(text="你现在没有老婆, 因为咱的记录中找不到其他群友")
            return
        waifu_id = random.choice(group_member)
    retry = 0
    while not is_success and retry < 3:
        try:
            waifu = await context.bot.get_chat(waifu_id)
            is_success = True
        except Exception as e:
            logger.error(
                f"无法为 {update.effective_user.name} 获取id为 {waifu_id} 的waifu:\n{e.__class__.__name__}: {e}"
            )
            retry += 1
            await asyncio.sleep(1)
    if not is_success:
        await update.message.reply_text(text="你没能抽到老婆, 再试一次吧~")
        poped_value = context.chat_data["members_data"].pop(waifu_id, "群组数据中无该成员")
        logger.debug(f"移除: {poped_value}")
        return
    avatar = waifu.photo
    if avatar:
        avatar = await (await waifu.photo.get_big_file()).download_as_bytearray()
        avatar = bytes(avatar)
    try:
        if is_got_waifu:
            text = f"你今天已经抽过老婆了\! {waifu.mention_markdown_v2()} 是你今天的老婆\!"
        else:
            text = f"你今天的群友老婆是 {waifu.mention_markdown_v2()} \!"
    except TypeError:
        if is_got_waifu:
            text = f"你的老婆消失了...TA的id曾是: *{waifu_id}*"
        else:
            text = "你没能抽到老婆, 再试一次吧~"
        await update.message.reply_text(text=text, parse_mode="MarkdownV2")
        poped_value = context.chat_data["members_data"].pop(waifu_id, "群组数据中无该成员")
        logger.debug(f"移除: {poped_value}")
        return
    if not update.message:
        return
    if avatar:
        await update.message.reply_photo(
            photo=avatar,
            caption=text,
            parse_mode="MarkdownV2",
        )
    else:
        await update.message.reply_markdown_v2(text=text)
    if is_success:
        context.bot_data["today_waifu"][user_id][chat_id] = waifu.id
    logger.info(f"Bot: {text}")
