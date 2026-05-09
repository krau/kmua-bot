from pydantic import BaseModel
from pydantic_ai import RunContext

from kmua import common, database
from kmua.config import app_config
from kmua.logger import logger

from .. import datatype


class ChatInfo(BaseModel):
    chat_id: int
    title: str
    config: dict | str | None = None
    members_count: int | None = None
    admins_count: int | None = None
    linked_channel: str | None = None
    description: str | None = None
    username: str | None = None


async def get_chat_info(ctx: RunContext[datatype.ContextDeps]) -> ChatInfo | None:
    """Get chat(group) full infomation.

    Returns:
        ChatInfo object if session in a chat and chat exists in database,
        None otherwise.
    """
    chat_id = ctx.deps.chat_id
    chat_title = ""
    chat_username = None
    chat_config = {}
    logger.debug(f"Fetching chat info for chat_id: {ctx.deps.chat_id}")
    if chat_id == ctx.deps.user_id:
        user_db = await database.get_user_by_id(ctx.deps.user_id)
        if user_db is None:
            return None
        chat_title = user_db.full_name
        chat_username = user_db.username
        chat_config = user_db.config
    else:
        chat_db = await database.get_chat_by_id(ctx.deps.chat_id)
        if chat_db is None:
            return None
        chat_title = chat_db.title
        chat_username = chat_db.username
        chat_config = chat_db.config
    if ctx.deps.is_guest_mode:
        return ChatInfo(
            chat_id=chat_id,
            title=chat_title,
            username=chat_username,
            config=chat_config,
        )
    chat_full = await common.memttlcache.get(f"chatfull_{chat_id}", None)
    if not chat_full:
        chat_full = await ctx.deps.client.get_chat(chat_id)
        await common.memttlcache.set(
            f"chatfull_{chat_id}", chat_full, app_config.cachettl_chatfull
        )
    return ChatInfo(
        chat_id=chat_id,
        title=chat_title,
        username=chat_username,
        config=chat_config,
        description=chat_full.description or chat_full.bio,
        linked_channel=chat_full.linked_chat.title if chat_full.linked_chat else None,
        members_count=chat_full.members_count
        if isinstance(chat_full.members_count, int)
        else None,
        admins_count=chat_full.admins_count
        if isinstance(chat_full.admins_count, int)
        else None,
    )
