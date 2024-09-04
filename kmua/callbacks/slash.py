import re

from telegram import (
    Update,
)
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown

from kmua import common
from kmua.logger import logger


def _replace_char(text: str):
    text = text.replace("$", "").replace("/", "").replace("\\", "")
    return text


async def slash(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if update.message_reaction:
        return
    message = update.effective_message
    if message.text.startswith("/"):
        if not message.text.startswith("//"):
            if re.match(r"^/[a-zA-Z0-9]+", message.text):
                return
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {message.text}"
    )
    cmd1 = ""
    cmd2 = ""
    text = ""
    this_user = message.sender_chat if message.sender_chat else message.from_user
    this_mention = common.mention_markdown_v2(this_user)
    replied_user = None
    replied_mention = ""
    if reply_to_message := update.effective_message.reply_to_message:
        replied_user = (
            reply_to_message.sender_chat
            if reply_to_message.sender_chat
            else reply_to_message.from_user
        )
        replied_mention = common.mention_markdown_v2(replied_user)
    is_backslash = (
        False
        if message.text.startswith("/")
        else True if message.text.startswith("\\") else None
    )
    if is_backslash is None:
        return
    is_one_cmd = len(message.text.split(" ")) == 1
    cmd1 = escape_markdown(_replace_char(message.text.split(" ")[0][1:]), 2)
    if not cmd1:
        return
    if not is_one_cmd:
        cmd2 = escape_markdown(_replace_char(" ".join(message.text.split(" ")[1:])), 2)
        text = (
            (
                rf"{replied_mention} {cmd1} {this_mention} {cmd2} \!"
                if replied_user
                else rf"{this_mention} {cmd1}自己{cmd2} \!"  # 好像和line73一样, 暂时没有其他 idea
            )
            if is_backslash
            else (
                rf"{this_mention} {cmd1} {replied_mention} {cmd2} \!"
                if replied_user
                else rf"{this_mention} {cmd1}自己{cmd2} \!"
            )
        )
    else:
        text = (
            (
                rf"{this_mention} 被 {replied_mention} {cmd1}了 \!"
                if replied_user
                else rf"{this_mention} 被自己{cmd1}了 \!"
            )
            if is_backslash
            else (
                rf"{this_mention} {cmd1}了 {replied_mention} \!"
                if replied_user
                else rf"{this_mention} {cmd1}了自己 \!"
            )
        )
    # 在中英文之间加空格
    text = re.sub(r"([a-zA-Z0-9])([\u4e00-\u9fa5])", r"\1 \2", text)
    text = re.sub(r"([\u4e00-\u9fa5])([a-zA-Z0-9])", r"\1 \2", text)
    await update.effective_message.reply_markdown_v2(
        text, disable_web_page_preview=True
    )
