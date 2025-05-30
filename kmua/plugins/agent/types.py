from dataclasses import dataclass

import pyrogram


@dataclass
class ContextDeps:
    client: pyrogram.Client
    user_id: int
    chat_id: int | None = None
    message_id: int | None = None
