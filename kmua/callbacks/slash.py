import re

from pyrogram import Client, enums, types

from kmua import common
from kmua.logger import logger


def replace_special_char(text: str):
    text = text.replace("$", "").replace("/", "").replace("\\", "")
    return text


async def slash(client: Client, message: types.Message):
    if message.entities:
        if message.entities[0].type == enums.MessageEntityType.BOT_COMMAND:
            return
    if len(message.text) > 100:
        return
    user = message.sender_chat or message.from_user
    logger.info(f"[{user.username or user.full_name}]: {message.text}")
    user_mention = (
        f"[{common.escape_markdown(user.full_name)}](tg://user?id={user.id})"
        if not user.username
        else f"[{common.escape_markdown(user.full_name)}](https://t.me/{user.username})"
    )
    target = None
    target_mention = ""
    if reply := message.reply_to_message:
        target = reply.sender_chat or reply.from_user
        target_mention = (
            f"[{common.escape_markdown(target.full_name)}](tg://user?id={target.id})"
            if not target.username
            else f"[{common.escape_markdown(target.full_name)}](https://t.me/{target.username})"
        )
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
    cmd1 = ""
    cmd2 = ""
    text = ""
    cmd1 = common.escape_markdown(replace_special_char(message.text.split(" ")[0][1:]))
    if not cmd1:
        return
    if not is_one_cmd:
        cmd2 = common.escape_markdown(
            replace_special_char(" ".join(message.text.split(" ")[1:]))
        )
        text = (
            (
                f"{target_mention} {cmd1} {user_mention} {cmd2} !"
                if target
                else f"{user_mention} {cmd1}自己{cmd2} !"  # 好像和line73一样, 暂时没有其他 idea
            )
            if is_backslash
            else (
                f"{user_mention} {cmd1} {target_mention} {cmd2} !"
                if target
                else f"{user_mention} {cmd1}自己{cmd2} !"
            )
        )
    else:
        text = (
            (
                f"{user_mention} 被 {target_mention} {cmd1}了 !"
                if target
                else f"{user_mention} 被自己{cmd1}了 !"
            )
            if is_backslash
            else (
                f"{user_mention} {cmd1}了 {target_mention} !"
                if target
                else f"{user_mention} {cmd1}了自己 !"
            )
        )
    # 在中英文之间加空格
    text = re.sub(r"([a-zA-Z0-9])([\u4e00-\u9fa5])", r"\1 \2", text)
    text = re.sub(r"([\u4e00-\u9fa5])([a-zA-Z0-9])", r"\1 \2", text)
    msg = await message.reply_text(
        text, parse_mode=enums.ParseMode.MARKDOWN, disable_web_page_preview=True
    )
    logger.info(f"[{message.chat.username or message.chat.title}](Bot): {msg.text}")
