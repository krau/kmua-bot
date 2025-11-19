from dataclasses import dataclass
from datetime import datetime

from pyrogram.client import Client as PyrogramClient
from pyrogram.enums.chat_type import ChatType
from pyrogram.types import Message

from kmua.database.models import UserData


@dataclass
class ContextDeps:
    client: PyrogramClient
    user_id: int
    chat_id: int
    message: Message


@dataclass
class UserData:
    user_id: int
    full_name: str
    username: str | None = None
    config: dict | None = None


@dataclass
class ContextInfo:
    user_data: UserData
    msg_id: int
    chat_type: str | None = None
    reply_to_msg_text: str | None = None
    reply_to_msg_id: int | None = None
    current_time: datetime | None = None
