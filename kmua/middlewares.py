from telegram import Update
from telegram.ext import ContextTypes, TypeHandler
from kmua import common, dao
from kmua.logger import logger
from telegram.constants import ChatType, ChatID


async def store_data(update: Update, _: ContextTypes):
    user = update.effective_user
    chat = update.effective_chat
    message = update.effective_message
    if not user or not chat or not message:
        return
    if chat.type == ChatType.CHANNEL or user.id == ChatID.SERVICE_CHAT:
        return
    if message.sender_chat:
        user = message.sender_chat
    db_user = dao.add_user(user)
    if chat.type in (chat.GROUP, chat.SUPERGROUP):
        dao.add_chat(chat)
        dao.add_association_in_chat(chat, db_user)


_enable_search = common.meili_client is not None and common.redis_client is not None


async def store_message(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not _enable_search:
        return
    user = update.effective_user
    chat = update.effective_chat
    message = update.effective_message
    if not user or not chat or not message:
        return
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    message = update.effective_message
    if not message:
        return
    if not (
        message.text
        or message.caption
        or message.document
        or message.photo
        or message.video
        or message.audio
    ):
        return
    if (
        update.callback_query
        or update.inline_query
        or update.chosen_inline_result
        or update.poll
        or update.poll_answer
        or update.chat_member
        or update.my_chat_member
        or update.shipping_query
        or update.chat_boost
        or update.chat_join_request
        or update.message_reaction
    ):
        return
    if not dao.get_chat_message_search_enabled(chat):
        return
    if message.sender_chat:
        user = message.sender_chat
    message_type = common.MessageType.TEXT
    text = ""
    if message.text:
        if message.text.startswith("/search"):
            return
        text += message.text
    if message.caption:
        text += " " + message.caption
    if message.document:
        text += " " + message.document.file_name
        message_type = common.MessageType.FILE
    if message.photo:
        message_type = common.MessageType.PHOTO
    if message.video:
        message_type = common.MessageType.VIDEO
        if message.video.file_name:
            text += " " + message.video.file_name
    if message.audio:
        message_type = common.MessageType.AUDIO
        if message.audio.title:
            text += " " + message.audio.title
        if message.audio.file_name:
            text += " " + message.audio.file_name
    if not text:
        return
    try:
        common.meili_client.index(f"kmua_{chat.id}").add_documents(
            [
                common.MessageInMeili(
                    message_id=message.id,
                    user_id=user.id,
                    text=text,
                    type=message_type,
                ).to_dict()
            ]
        )
    except Exception as e:
        logger.warning(f"add document error: {e.__class__.__name__}: {e}")


store_data_handler = TypeHandler(Update, store_data)
add_message_handler = TypeHandler(Update, store_message)

before_middleware = [store_data_handler]
after_middleware = [add_message_handler]
