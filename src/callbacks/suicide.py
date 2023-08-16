import random

from telegram import Update
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown

from ..config.config import settings
from ..logger import logger
from ..utils import message_recorder, parse_arguments


async def suicide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    music = context.bot_data["music"]
    if not music:
        return
    music = random.choice(context.bot_data["music"])
    lrc = music["lrc"]
    url = music["url"]
    if not url:
        text = escape_markdown(lrc, 2)
    else:
        text = f"[{escape_markdown(lrc,2)}]({escape_markdown(url,2)})"
    await update.effective_message.reply_markdown_v2(
        text=text,
        disable_web_page_preview=True,
    )
    await message_recorder(update, context)
    logger.info(f"Bot: {text}")


async def add_music(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in settings.owners:
        return
    text = " ".join(context.args)
    args = parse_arguments(text)
    match len(args):
        case 1:
            await _add_music_without_url(update, context, args)
        case 2:
            await _add_music_with_url(update, context, args)
        case _:
            await update.effective_message.reply_text(
                text="参数错误",
            )


async def _add_music_without_url(
    update: Update, context: ContextTypes.DEFAULT_TYPE, args: list[str]
):
    new_music = {
        "lrc": args[0],
        "url": None,
    }
    context.bot_data["music"].append(new_music)
    await update.effective_message.reply_text(
        text="添加成功:\n" + str(new_music),
    )


async def _add_music_with_url(
    update: Update, context: ContextTypes.DEFAULT_TYPE, args: list[str]
):
    new_music = {
        "lrc": args[0],
        "url": args[1],
    }
    context.bot_data["music"].append(new_music)
    await update.effective_message.reply_text(
        text="添加成功:\n" + str(new_music),
    )


async def clear_music(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in settings.owners:
        return
    context.bot_data["music"] = []
    await update.effective_message.reply_text(
        text="已清空",
    )
