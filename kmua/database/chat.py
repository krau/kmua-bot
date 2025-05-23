from pyrogram.types import Chat

from .db import get_session
from .models import ChatData, ChatConfig


async def upsert_chat(chat: Chat) -> ChatData:
    async with get_session() as session:
        async with session.begin():
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
                session.expunge(chat_data)
            return chat_data


async def get_chat_by_id(chat_id: int) -> ChatData | None:
    async with get_session() as session:
        async with session.begin():
            chat_data = await session.get(ChatData, chat_id)
            if chat_data is None:
                return None
            session.expunge(chat_data)
            return chat_data


async def get_chat_config(chat: int | ChatData | Chat) -> ChatConfig:
    if isinstance(chat, ChatData):
        return ChatConfig.from_dict(chat.config)
    elif isinstance(chat, Chat):
        chat_data = await upsert_chat(chat)
    elif isinstance(chat, int):
        chat_data = await get_chat_by_id(chat)
    else:
        raise TypeError("chat must be int, ChatData or Chat")
    if chat_data is None:
        raise ValueError("Chat not found")
    return ChatConfig.from_dict(chat_data.config)
