from pyrogram import Client
from pyrogram.enums import ChatType
from pyrogram.types import Message

from kmua import database


@Client.on_message(group=-1)
async def store_data(client: Client, message: Message):
    user = message.from_user or message.sender_chat
    chat = message.chat
    if user is None or chat is None:
        return
    if chat.type == ChatType.CHANNEL:
        return
    user_db = await database.upsert_user(user)
    if chat.type in (ChatType.SUPERGROUP, ChatType.GROUP):
        chat_db = await database.upsert_chat(chat)
        await database.add_association_in_chat(chat_db, user_db, None)
