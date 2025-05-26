import aiocache
import cachetools
from pyrogram.types import Chat
from sqlalchemy.ext.asyncio import AsyncSession

from .db import with_session, with_tx
from .models import ChatConfig, ChatData


@with_tx
async def upsert_chat(chat: Chat, session: AsyncSession | None = None) -> ChatData:
    chat_data = await session.get(ChatData, chat.id)
    if chat_data is None:
        chat_data = ChatData(
            id=chat.id,
            title=chat.title,
            username=chat.username,
        )
        session.add(chat_data)
    else:
        chat_data.title = chat.title  # type: ignore
        chat_data.username = chat.username  # type: ignore
    return chat_data


@with_session
async def get_chat_by_id(
    chat_id: int, session: AsyncSession | None = None
) -> ChatData | None:
    chat_data = await session.get(ChatData, chat_id)
    if chat_data is None:
        return None
    return chat_data


async def get_chat_config(chat: int | ChatData | Chat) -> ChatConfig:
    if isinstance(chat, ChatData):
        return chat.chat_config
    chat_data: ChatData | None = None
    if isinstance(chat, Chat):
        chat_data = await upsert_chat(chat)
    elif isinstance(chat, int):
        chat_data = await get_chat_by_id(chat)
    else:
        raise TypeError("chat must be int, ChatData or Chat")
    if chat_data is None:
        raise ValueError("Chat not found")
    return chat_data.chat_config


@with_tx
async def update_chat_config(
    chat: int | ChatData | Chat, config: ChatConfig, session: AsyncSession | None = None
) -> ChatConfig:
    chat_id = 0
    if isinstance(chat, ChatData):
        chat_id = chat.id
    elif isinstance(chat, Chat):
        chat_id = chat.id
    elif isinstance(chat, int):
        chat_id = chat
    else:
        raise TypeError("chat must be int, ChatData or Chat")

    chat_data = await session.get(ChatData, chat_id)
    if chat_data is None:
        if isinstance(chat, Chat):
            chat_data = ChatData(
                id=chat.id,
                title=chat.title,
                username=chat.username,
            )
            session.add(chat_data)
            await session.flush()
        else:
            raise ValueError(f"Chat with id {chat_id} not found")
    chat_data.chat_config = config
    return chat_data.chat_config
