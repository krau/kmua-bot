from telegram import (
    Update,
)
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown
from ..logger import logger
from ..common.message import message_recorder
import re


def replace_special_char(text: str):
    text = text.replace("$", "").replace("/", "").replace("\\", "")
    return text


async def interact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    cmd1 = ""
    cmd2 = ""
    text = ""
    message = update.effective_message
    this_user = message.sender_chat if message.sender_chat else message.from_user
    try:
        this_mention = this_user.mention_markdown_v2()
    except TypeError:
        this_mention = (
            f"[{escape_markdown(this_user.title,2)}](tg://user?id={this_user.id})"
        )
    replied_user = None
    replied_mention = ""
    if reply_to_message := update.effective_message.reply_to_message:
        replied_user = (
            reply_to_message.sender_chat
            if reply_to_message.sender_chat
            else reply_to_message.from_user
        )
        try:
            replied_mention = replied_user.mention_markdown_v2()
        except TypeError:
            replied_mention = f"[{escape_markdown(replied_user.title,2)}](tg://user?id={replied_user.id})"
    is_backslash = (
        False
        if message.text.startswith("/")
        else True
        if message.text.startswith("\\")
        else None
    )
    if is_backslash is None:
        return
    is_one_cmd = True if len(message.text.split(" ")) == 1 else False
    cmd1 = escape_markdown(replace_special_char(message.text.split(" ")[0][1:]), 2)
    if not is_one_cmd:
        cmd2 = escape_markdown(
            replace_special_char(" ".join(message.text.split(" ")[1:])), 2
        )
        text = (
            (
                f"{this_mention} 被 {replied_mention} {cmd1}{cmd2} \!"
                if replied_user
                else f"{this_mention} 被自己{cmd1}{cmd2} \!"
            )
            if is_backslash
            else (
                f"{this_mention} {cmd1} {replied_mention} {cmd2} \!"
                if replied_user
                else f"{this_mention} {cmd1}自己{cmd2} \!"
            )
        )
    else:
        text = (
            (
                f"{this_mention} 被 {replied_mention} {cmd1}了 \!"
                if replied_user
                else f"{this_mention} 被自己{cmd1}了 \!"
            )
            if is_backslash
            else (
                f"{this_mention} {cmd1}了 {replied_mention} \!"
                if replied_user
                else f"{this_mention} {cmd1}了自己 \!"
            )
        )
    # 在中英文之间加空格
    text = re.sub(r"([a-zA-Z0-9])([\u4e00-\u9fa5])", r"\1 \2", text)
    text = re.sub(r"([\u4e00-\u9fa5])([a-zA-Z0-9])", r"\1 \2", text)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        parse_mode="MarkdownV2",
    )
    await message_recorder(update, context)
