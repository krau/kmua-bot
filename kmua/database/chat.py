from pyrogram.types import Chat

from .db import get_session
from .models import ChatData


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
