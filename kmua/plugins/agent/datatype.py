from dataclasses import dataclass

import pyrogram


@dataclass
class ContextDeps:
    client: pyrogram.Client
    user_id: int
    chat_id: int
    message: pyrogram.types.Message
