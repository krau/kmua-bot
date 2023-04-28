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
    message_text = update.effective_message.text
    if reply_to_message := update.effective_message.reply_to_message:
        # 如果是对其他人使用
        this_user = update.effective_user
        replied_user = reply_to_message.from_user
        this_name = this_user.full_name
        replied_name = replied_user.full_name
        this_id = this_user.id
        replied_id = replied_user.id
        if len(message_text.split(" ")) == 1:
            if message_text.startswith("/"):
                cmd = message_text[1:].replace("/", "")
                text = f"[{this_name}](tg://user?id={this_id}){cmd}了[{replied_name}](tg://user?id={replied_id})!"  # noqa: E501

            elif message_text.startswith("\\"):
                cmd = message_text[1:]
                text = f"[{this_name}](tg://user?id={this_id})被[{replied_name}](tg://user?id={replied_id}){cmd}了!"  # noqa: E501
        else:
            if message_text.startswith("/"):
                cmd_front = message_text.split(" ")[0].replace("/", "")
                cmd_back = message_text.split(" ")[1:]
                cmd_back = " ".join(cmd_back).replace("/", "")
                text = f"[{this_name}](tg://user?id={this_id}){cmd_front}[{replied_name}](tg://user?id={replied_id}){cmd_back}!"  # noqa: E501
            elif message_text.startswith("\\"):
                cmd_front = message_text.split(" ")[0].replace("\\", "")
                cmd_back = message_text.split(" ")[1:]
                cmd_back = " ".join(cmd_back)
                text = f"[{replied_name}](tg://user?id={replied_id}){cmd_front}[{this_name}](tg://user?id={this_id}){cmd_back}!"  # noqa: E501
    else:
        # 如果是对自己使用
        if message_text.startswith("/"):
            cmd = message_text[1:].replace("/", "")
            text = f"[{update.effective_user.full_name}](tg://user?id={update.effective_user.id}){cmd}了自己!"  # noqa: E501
        elif message_text.startswith("\\"):
            cmd = message_text[1:]
            text = f"[{update.effective_user.full_name}](tg://user?id={update.effective_user.id})被自己{cmd}了!"  # noqa: E501
    sent_message = await context.bot.send_message(
        chat_id=update.effective_chat.id, text=text, parse_mode="Markdown"
    )
    logger.info(f"Bot: {sent_message.text}")
