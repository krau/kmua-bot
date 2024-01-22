from telegram import Message, Update
from telegram.constants import ChatID, ChatType
from telegram.ext import ContextTypes

from kmua import dao
from kmua.logger import logger


def message_recorder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    message = update.effective_message
    if not user or not chat or not message:
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
        dao.add_chat(chat)
        dao.add_association_in_chat(chat, db_user)


def get_message_common_link(message: Message) -> str | None:
    logger.debug(f"Get message common link for {message.link}")
    try:
        chat = message.chat
        link = f"https://t.me/c/{str(chat.id).removeprefix('-100')}/{message.id}"
        return link
    except Exception as e:
        logger.error(f"{e.__class__.__name__}: {e}")
        return None


def parse_message_link(link: str) -> tuple[int, int]:
    logger.debug(f"Parse message link for {link}")
    split_link = link.split("/")
    try:
        chat_id = int("-100" + split_link[-2])
        message_id = int(split_link[-1])
    except ValueError:
        logger.error(f"无法解析链接: {link}")
        return None, None
    return chat_id, message_id
