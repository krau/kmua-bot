import datetime
import html
from dataclasses import dataclass

import pyrogram
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.types import Chat, User

from kmua import database, enums
from kmua.bot import client
from kmua.common import client
from kmua.config import app_config
from kmua.database.models import ChatData, UserData
from kmua.logger import logger

from .memory_store import memttlcache


def chat_message_cache_key(chat_id: int, message_id: int) -> str:
    """Generate a cache key for a chat message."""
    return f"chat_history:{chat_id}:{message_id}"


@dataclass
class HistoryMessage:
    message_id: int
    chat_id: int
    user_id: int
    text: str
    time: datetime.datetime | None


async def get_messages_with_cache(
    chat_id: int,
    message_ids: list[int],
    reply: bool = False,
    pinned: bool = False,
    replies: int = 1,
) -> list[HistoryMessage]:
    logger.debug(f"Fetching {len(message_ids)} messages for {chat_id}")
    to_fetch_ids = []
    cached_messages: dict[int, HistoryMessage] = {}
    for i in message_ids:
        cached_msg = await memttlcache.get(chat_message_cache_key(chat_id, i), None)
        if cached_msg is not None:
            cached_messages[i] = cached_msg
        else:
            to_fetch_ids.append(i)
    fetched_messages: list[pyrogram.types.Message] = []
    if to_fetch_ids:
        fetched = await client.get_messages(
            chat_id=chat_id,
            message_ids=to_fetch_ids,
            reply=reply,
            pinned=pinned,
            replies=replies,
        )

        if isinstance(fetched, pyrogram.types.Message):
            fetched = [fetched]
        fetched_messages.extend(fetched or [])
    history_messages = [
        HistoryMessage(
            message_id=msg.id,
            chat_id=msg.chat.id if msg.chat and msg.chat.id else 0,
            user_id=(
                msg.sender_chat.id
                if msg.sender_chat and msg.sender_chat.id is not None
                else msg.from_user.id
                if msg.from_user and msg.from_user.id is not None
                else 0
            ),
            text=msg.text or msg.caption or "",
            time=msg.date,
        )
        for msg in fetched_messages
        if (msg.sender_chat or msg.from_user) and (msg.text or msg.caption)
    ]
    history_messages.extend(cached_messages.values())
    for msg in history_messages:
        await memttlcache.set(
            chat_message_cache_key(chat_id, msg.message_id),
            msg,
            ttl=app_config.cachettl_history_message,
        )
    history_messages.sort(key=lambda x: 0 if x.time is None else x.time.timestamp())
    return history_messages


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
    if chat_member.status == ChatMemberStatus.ADMINISTRATOR:
        if (
            chat_member.privileges is not None
            and chat_member.privileges.can_promote_members
        ):
            return True
    return False


def get_message_origin(
    message: pyrogram.types.Message,
) -> pyrogram.types.User | pyrogram.types.Chat | None:
    if origin := message.forward_origin:
        match origin.type:
            case pyrogram.enums.MessageOriginType.USER:
                return origin.sender_user  # type: ignore
            case pyrogram.enums.MessageOriginType.CHANNEL:
                return origin.chat  # type: ignore
            case pyrogram.enums.MessageOriginType.CHAT:
                return origin.sender_chat  # type: ignore
    return message.sender_chat or message.from_user
