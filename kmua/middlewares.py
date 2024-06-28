import pickle

from telegram import Update
from telegram.constants import ChatID, ChatType
from telegram.ext import ContextTypes, TypeHandler

from kmua import common, dao
from kmua.callbacks.search import update_index_job
from kmua.logger import logger


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


async def store_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    if not context.job_queue.get_jobs_by_name(f"update_index_{chat.id}"):
        context.job_queue.run_repeating(
            update_index_job, 300, chat_id=chat.id, name=f"update_index_{chat.id}"
        )
    for entity in message.entities:
        if entity.type == entity.BOT_COMMAND:
            return
    if message.sender_chat:
        user = message.sender_chat
    message_type = common.MessageType.TEXT
    text = ""
    if message.text:
        text += message.text
    if message.caption:
        text += " " + message.caption
    if message.document:
        message_type = common.MessageType.FILE
        if message.document.file_name:
            text += " " + message.document.file_name
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
        if context.chat_data.get("updating_index"):
            if not context.chat_data.get("pending_messages"):
                context.chat_data["pending_messages"] = []
            context.chat_data["pending_messages"].append(
                common.MessageInMeili(
                    message_id=message.message_id,
                    text=text,
                    user_id=user.id,
                    type=message_type,
                )
            )
            return
        if context.chat_data.get("pending_messages"):
            for pending_message in context.chat_data["pending_messages"]:
                common.redis_client.rpush(
                    f"kmua_chatmsg_{chat.id}", pickle.dumps(pending_message)
                )
            context.chat_data["pending_messages"] = []
        common.redis_client.rpush(
            f"kmua_chatmsg_{chat.id}",
            pickle.dumps(
                common.MessageInMeili(
                    message_id=message.message_id,
                    text=text,
                    user_id=user.id,
                    type=message_type,
                )
            ),
        )
    except Exception as e:
        logger.warning(f"saving message to failed: {e.__class__.__name__}: {e}")


store_data_handler = TypeHandler(Update, store_data)

before_middleware = [store_data_handler]
after_middleware = []

if _enable_search:
    store_message_handler = TypeHandler(Update, store_message)
    after_middleware.append(store_message_handler)
