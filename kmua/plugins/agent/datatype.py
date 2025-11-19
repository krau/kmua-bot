from dataclasses import dataclass

from pyrogram.client import Client as PyrogramClient
from pyrogram.enums.chat_type import ChatType
from pyrogram.types import Message


@dataclass
class ContextDeps:
    client: PyrogramClient
    user_id: int
    chat_id: int
    message: Message


@dataclass
class ContextInfo:
    user_id: int
    msg_id: int
    chat_type: ChatType | None = None
    reply_to_msg_text: str | None = None
    reply_to_msg_id: int | None = None
