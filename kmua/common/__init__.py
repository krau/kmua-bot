import html

import pyrogram
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.types import Chat, User

from kmua import database, enums
from kmua.bot import client
from kmua.database.models import ChatData, UserData

from .avatar import *
from .jobs import jobqueue  # noqa: F401
from .memory_store import memstore, memttlcache  # noqa: F401


async def mention_html(chat: User | Chat | UserData | ChatData) -> str:
    if isinstance(chat, ChatData):
        raise NotImplementedError
    db_user = await database.upsert_user(chat)
    if not db_user.is_real_user and db_user.username and db_user.full_name:
        return f"<a href='https://t.me/{db_user.username}'>{html.escape(db_user.full_name)}</a>"
    return f"<a href='tg://user?id={chat.id}'>{html.escape(chat.full_name)}</a>"


async def can_user_manage_bot_in_chat(
    user: User | Chat | int, chat: Chat | int
) -> bool:
    if isinstance(chat, Chat):
        if chat.type == ChatType.PRIVATE:
            raise ValueError("Chat must not be private")
    user_id = user.id if isinstance(user, (User, Chat)) else user
    chat_id = chat.id if isinstance(chat, Chat) else chat
    if not user_id or not chat_id:
        raise ValueError("User ID and Chat ID must not be None")
    if user_id == enums.ChatID.ANONYMOUS_ADMIN:
        return True
    db_user = await database.get_user_by_id(user_id)
    if db_user is None:
        raise ValueError("User not found")
    if db_user.is_bot_global_admin:
        return True
    association = await database.get_association(user_id, chat_id)
    if association is None:
        return False
    if association.is_bot_admin:
        return True
    chat_member = await client.get_chat_member(chat_id, user_id)
    if chat_member.status == ChatMemberStatus.OWNER:
        association.is_bot_admin = True
        await database.update_association(association)
        return True
    return False


def get_message_origin(
    message: pyrogram.types.Message,
) -> pyrogram.types.User | pyrogram.types.Chat | None:
    if origin := message.forward_origin:
        match origin.type:
            case pyrogram.enums.MessageOriginType.USER:
                return origin.sender_user
            case pyrogram.enums.MessageOriginType.CHANNEL:
                return origin.chat
            case pyrogram.enums.MessageOriginType.CHAT:
                return origin.sender_chat
    return message.sender_chat or message.from_user
