from pydantic import BaseModel
from pydantic_ai import RunContext

from kmua import common, database
from kmua.logger import logger

from .. import datatype


class UserInfo(BaseModel):
    user_id: int
    full_name: str
    config: dict
    username: str | None = None


async def get_user_info(ctx: RunContext[datatype.ContextDeps]) -> UserInfo | None:
    logger.debug("Fetching user info for user_id: %s", ctx.deps.user_id)
    user_db = await database.get_user_by_id(ctx.deps.user_id)
    if user_db is None:
        return None
    return UserInfo(
        user_id=user_db.id,
        full_name=user_db.full_name,
        username=user_db.username,
        config=user_db.config,
    )


class ChatInfo(BaseModel):
    chat_id: int
    title: str
    config: dict
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
    
    if ctx.deps.chat_id is None:
        return None
    logger.debug("Fetching chat info for chat_id: %s", ctx.deps.chat_id)
    chat_db = await database.get_chat_by_id(ctx.deps.chat_id)
    if chat_db is None:
        return None
    chat_full = await common.memttlcache.get(f"chatfull_{chat_db.id}", None)
    if not chat_full:
        chat_full = await ctx.deps.client.get_chat(chat_db.id)
        await common.memttlcache.set(f"chatfull_{chat_db.id}", chat_full, 86400)
    return ChatInfo(
        chat_id=chat_db.id,
        title=chat_db.title,
        username=chat_db.username,
        config=chat_db.config,
        description=chat_full.description or chat_full.bio,
        linked_channel=chat_full.linked_chat.title if chat_full.linked_chat else None,
        members_count=chat_full.members_count
        if isinstance(chat_full.members_count, int)
        else None,
        admins_count=chat_full.admins_count
        if isinstance(chat_full.admins_count, int)
        else None,
    )
