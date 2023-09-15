from telegram import Message, Update
from telegram.constants import ChatType, ChatID
from telegram.ext import ContextTypes

from ..database import dao
from ..logger import logger


async def message_recorder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    message = update.effective_message
    if not user or not chat:
        return
    if (
        message.reply_to_message
        or chat.type == ChatType.CHANNEL
        or user.id == ChatID.SERVICE_CHAT
    ):
        return
    if message.sender_chat:
        user = message.sender_chat
    db_user = dao.add_user(user)
    if chat.type == ChatType.GROUP or chat.type == ChatType.SUPERGROUP:
        dao.add_user_to_chat(db_user, chat)


def get_message_common_link(message: Message) -> str:
    chat = message.chat
    if chat.username:
        link = f"https://t.me/c/{str(chat.id).removeprefix('-100')}/{message.id}"
    else:
        link = message.link
    return link


def parse_message_link(link: str) -> tuple[int, int]:
    split_link = link.split("/")
    try:
        chat_id = int("-100" + split_link[-2])
        message_id = int(split_link[-1])
    except ValueError:
        logger.error(f"无法解析链接: {link}")
        return None, None
    return chat_id, message_id
