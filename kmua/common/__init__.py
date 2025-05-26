import html

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
    if not db_user.is_real_user and db_user.username is not None:
        return f"<a href='https://t.me/{db_user.username}'>{html.escape(db_user.full_name)}</a>"
    return f"<a href='tg://user?id={chat.id}'>{html.escape(chat.full_name)}</a>"


async def can_user_manage_bot_in_chat(user: User, chat: Chat) -> bool:
    if chat.type == ChatType.PRIVATE:
        raise ValueError("Chat must not be private")
    if user.id == enums.ChatID.ANONYMOUS_ADMIN:
        return True
    db_user = await database.get_user_by_id(user.id)
    if db_user is None:
        raise ValueError("User not found")
    if db_user.is_bot_global_admin:
        return True
    association = await database.get_association(user.id, chat.id)
    if association is None:
        return False
    if association.is_bot_admin:
        return True
    chat_member = await client.get_chat_member(chat.id, user.id)
    if chat_member.status == ChatMemberStatus.OWNER:
        association.is_bot_admin = True
        await database.update_association(user.id, chat.id, association)
        return True
    return False
