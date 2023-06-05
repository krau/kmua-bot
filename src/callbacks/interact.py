from telegram import (
    Update,
)
from telegram.ext import ContextTypes

from ..logger import logger
from ..utils import message_recorder


async def interact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    await message_recorder(update, context)
    text = ""
    cmd = ""
    message = update.effective_message
    this_is_chat = True if message.sender_chat else False
    this_user = update.effective_user
    this_name = this_user.full_name
    this_id = this_user.id
    this_link = f"[{this_name}](tg://user?id={this_id})"
    if this_is_chat:
        this_user = message.sender_chat
        this_name = this_user.title
        this_id = this_user.username
        this_link = f"[{this_name}](https://t.me/{this_id})"
    if reply_to_message := update.effective_message.reply_to_message:
        # 如果是对其他人使用
        replied_is_chat = True if reply_to_message.sender_chat else False
        replied_user = reply_to_message.from_user
        replied_name = replied_user.full_name
        replied_id = replied_user.id
        replied_link = f"[{replied_name}](tg://user?id={replied_id})"
        if replied_is_chat:
            replied_user = reply_to_message.sender_chat
            replied_name = replied_user.title
            replied_id = replied_user.username
            replied_link = f"[{replied_name}](https://t.me/{replied_id})"
        if len(message.text.split(" ")) == 1:
            if message.text.startswith("/"):
                cmd = message.text[1:].replace("/", "")
                text = f"{this_link}{cmd}了{replied_link}!"
            elif message.text.startswith("\\"):
                cmd = message.text[1:]
                text = f"{this_link}被{replied_link}{cmd}了!"
        else:
            if message.text.startswith("/"):
                cmd_front = message.text.split(" ")[0].replace("/", "")
                cmd_back = message.text.split(" ")[1:]
                cmd_back = " ".join(cmd_back).replace("/", "")
                text = f"{this_link}{cmd_front}{replied_link}{cmd_back}!"
            elif message.text.startswith("\\"):
                cmd_front = message.text.split(" ")[0].replace("\\", "")
                cmd_back = message.text.split(" ")[1:]
                cmd_back = " ".join(cmd_back)
                text = f"{replied_link}{cmd_front}{this_link}{cmd_back}!"
    else:
        # 如果是对自己使用
        if len(message.text.split(" ")) == 1:
            if message.text.startswith("/"):
                cmd = message.text[1:].replace("/", "")
                text = f"{this_link}{cmd}了自己!"
            elif message.text.startswith("\\"):
                cmd = message.text[1:]
                text = f"{this_link}被自己{cmd}了!"
        else:
            if message.text.startswith("/"):
                cmd_front = message.text.split(" ")[0].replace("/", "")
                cmd_back = message.text.split(" ")[1:]
                cmd_back = " ".join(cmd_back).replace("/", "")
                text = f"{this_link}{cmd_front}自己{cmd_back}!"
            elif message.text.startswith("\\"):
                cmd_front = message.text.split(" ")[0].replace("\\", "")
                cmd_back = message.text.split(" ")[1:]
                cmd_back = " ".join(cmd_back)
                text = f"{this_link}被自己{cmd_front}了{cmd_back}!"
    sent_message = await context.bot.send_message(
        chat_id=update.effective_chat.id, text=text, parse_mode="Markdown"
    )
    logger.info(f"Bot: {sent_message.text}")
