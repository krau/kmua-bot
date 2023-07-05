from telegram import (
    Update,
)
from telegram.ext import ContextTypes

from ..logger import logger
from ..utils import message_recorder, escape


async def interact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    text = ""
    cmd = ""
    message = update.effective_message
    this_is_chat = True if message.sender_chat else False
    this_user = update.effective_user
    if this_is_chat:
        this_user = message.sender_chat
    try:
        this_link = this_user.mention_markdown_v2()
    except TypeError:
        this_link = f"[{escape(this_user.title)}](tg://user?id={this_user.id})"
    if reply_to_message := update.effective_message.reply_to_message:
        # 如果是对其他人使用
        replied_is_chat = True if reply_to_message.sender_chat else False
        if replied_is_chat:
            replied_user = reply_to_message.sender_chat
        else:
            replied_user = reply_to_message.from_user
        try:
            replied_link = replied_user.mention_markdown_v2()
        except TypeError:
            replied_link = (
                f"[{escape(replied_user.title)}](tg://user?id={replied_user.id})"
            )
        if len(message.text.split(" ")) == 1:
            if message.text.startswith("/"):
                cmd = escape(message.text[1:])
                text = f"{this_link}{cmd}了{replied_link} \!"
            elif message.text.startswith("\\"):
                cmd = escape(message.text[1:])
                text = f"{this_link}被{replied_link}{cmd}了 \!"
        else:
            if message.text.startswith("/"):
                cmd_front = escape(message.text.split(" ")[0][1:])
                cmd_back = message.text.split(" ")[1:]
                cmd_back = " ".join(cmd_back).replace("/", "")
                cmd_back = escape(cmd_back)
                text = f"{this_link}{cmd_front}{replied_link}{cmd_back} \!"
            elif message.text.startswith("\\"):
                cmd_front = escape(message.text.split(" ")[0][1:])
                cmd_back = message.text.split(" ")[1:]
                cmd_back = " ".join(cmd_back)
                cmd_back = escape(cmd_back)
                text = f"{replied_link}{cmd_front}{this_link}{cmd_back} \!"
    else:
        # 如果是对自己使用
        if len(message.text.split(" ")) == 1:
            if message.text.startswith("/"):
                cmd = escape(message.text[1:])
                text = f"{this_link}{cmd}了自己\!"
            elif message.text.startswith("\\"):
                cmd = escape(message.text[1:])
                text = f"{this_link}被自己{cmd}了 \!"
        else:
            if message.text.startswith("/"):
                cmd_front = escape(message.text.split(" ")[0][1:])
                cmd_back = message.text.split(" ")[1:]
                cmd_back = " ".join(cmd_back).replace("/", "")
                cmd_back = escape(cmd_back)
                text = f"{this_link}{cmd_front}自己{cmd_back} \!"
            elif message.text.startswith("\\"):
                cmd_front = escape(message.text.split(" ")[0][1:])
                cmd_back = message.text.split(" ")[1:]
                cmd_back = " ".join(cmd_back)
                cmd_back = escape(cmd_back)
                text = f"{this_link}被自己{cmd_front}了{cmd_back} \!"
    sent_message = await context.bot.send_message(
        chat_id=update.effective_chat.id, text=text, parse_mode="MarkdownV2"
    )
    await message_recorder(update, context)
    logger.info(f"Bot: {sent_message.text}")
