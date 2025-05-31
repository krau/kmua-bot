from dataclasses import dataclass

import pyrogram


@dataclass
class ContextDeps:
    client: pyrogram.Client
    user_id: int
    chat_id: int | None = None
    message: pyrogram.types.Message | None = None
