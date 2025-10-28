from dataclasses import dataclass

from pyrogram.client import Client as PyrogramClient
from pyrogram.types import Message


@dataclass
class ContextDeps:
    client: PyrogramClient
    user_id: int
    chat_id: int
    message: Message
