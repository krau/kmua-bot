from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.types import CallbackQuery, ChatMemberUpdated, Message

from kmua import database
from kmua.logger import logger


@Client.on_message(group=-1)
async def on_m(client: Client, message: Message):
    user = message.sender_chat or message.from_user
    chat = message.chat
    if user is None or chat is None:
        return
    logger.debug(f"[{chat.id}]({user.id}): {message.text or message.caption}")
    if chat.type == ChatType.CHANNEL:
        message.stop_propagation()
    user_db = await database.upsert_user(user)
    if chat.type in (ChatType.SUPERGROUP, ChatType.GROUP):
        chat_db = await database.upsert_chat(chat)
        await database.add_association_in_chat(chat_db, user_db, None)


@Client.on_callback_query(group=-1)
async def on_cb(client: Client, callback_query: CallbackQuery):
    user = callback_query.from_user
    chat = callback_query.message.chat
    if user is None or chat is None:
        return
    logger.debug(f"[{chat.id}]({user.id}): {callback_query.data}")
    if chat.type == ChatType.CHANNEL:
        callback_query.stop_propagation()
    user_db = await database.upsert_user(user)
    if chat.type in (ChatType.SUPERGROUP, ChatType.GROUP):
        chat_db = await database.upsert_chat(chat)
        await database.add_association_in_chat(chat_db, user_db, None)


@Client.on_chat_member_updated(filters.group, group=-1)
async def chat_member_updated(client: Client, chat_member_updated: ChatMemberUpdated):
    """
    seems only group admin can receive this event
    """
    chat = chat_member_updated.chat
    old_obj = chat_member_updated.old_chat_member
    new_obj = chat_member_updated.new_chat_member
    """
    1. old_obj is None, new_obj.user is not None:
         This means a new user has joined the chat.
    2. old_obj is not None, new_obj is None:
        This means a user has left the chat.
    3. both old_obj and new_obj are not None, but new_obj.status == BANNED:
        This means a user has been banned from the chat.
    ---
    other cases we don't care about:
    4. new_obj is None, old_obj.status == BANNED:
        This means a user has been unbanned from the chat, but the user is not in the chat.
    5. old_obj is not None, new_obj is not None, new_obj.status != BANNED:
        This means a user has changed their status in the chat (e.g., from member to admin).
    """
    if not any((old_obj, new_obj)):
        return
    user = new_obj.user if new_obj else old_obj.user
    if user is None:
        return
    db_user = await database.upsert_user(user)
    db_chat = await database.upsert_chat(chat)
    if not db_user or not db_chat:
        return
    if old_obj is None and new_obj is not None:
        logger.info(f"[{chat.id}]({user.id}): {user.full_name} joined the chat")
        await database.add_association_in_chat(db_chat, db_user)
    elif (old_obj is not None and old_obj.user and new_obj is None) or (
        old_obj is not None
        and new_obj is not None
        and new_obj.status == ChatMemberStatus.BANNED
    ):
        logger.info(f"[{chat.id}]({user.id}): {user.full_name} left the chat")
        await database.remove_association(db_user.id, db_chat.id)
