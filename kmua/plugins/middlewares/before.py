from pyrogram import Client
from pyrogram.enums import ChatType
from pyrogram.types import CallbackQuery, Message

from kmua import database
from kmua.logger import logger


@Client.on_message(group=-1)
async def store_data(client: Client, message: Message):
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
async def store_data_on_callback(client: Client, callback_query: CallbackQuery):
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
