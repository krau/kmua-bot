import sqlalchemy
import sqlalchemy.dialects
import sqlalchemy.dialects.mysql
import sqlalchemy.dialects.postgresql
import sqlalchemy.dialects.sqlite
from pyrogram.types import Chat
from sqlalchemy.ext.asyncio import AsyncSession

from kmua.common.memory_store import memttlcache
from kmua.config import runtime_config
from kmua.database import pagination

from .db import with_session, with_tx
from .models import ChatConfig, ChatData, UserChatAssociation

# 本地内存缓存：记录已同步到 DB 的群组快照，避免每条消息触发重复 upsert
# key: chat_id, value: (title, username)
_upsert_chat_cache: dict[int, tuple] = {}

_CHAT_CONFIG_CACHE_TTL = 300  # 5 分钟
_CHAT_CONFIG_CACHE_PREFIX = "chat_config:"


@with_session
async def count_chats(session: AsyncSession | None = None) -> int:
    assert session is not None

    stmt = sqlalchemy.select(sqlalchemy.func.count()).select_from(ChatData)
    result = await session.execute(stmt)
    return result.scalar() or 0


@with_tx
async def upsert_chat(chat: Chat, session: AsyncSession | None = None) -> ChatData:
    assert session is not None

    if chat.id is None:
        raise ValueError("chat.id must not be None")
    chat_id: int = chat.id

    # 检查缓存：如果数据没有变化，直接从 DB 读取并返回，避免触发写事务
    cache_data = (chat.title, chat.username)
    if _upsert_chat_cache.get(chat_id) == cache_data:
        cached = await session.get(ChatData, chat_id)
        if cached is not None:
            return cached

    if runtime_config.db_is_postgres:
        stmt = (
            sqlalchemy.dialects.postgresql.insert(ChatData)
            .values(
                id=chat_id,
                title=chat.title,
                username=chat.username,
            )
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "title": chat.title,
                    "username": chat.username,
                },
            )
            .returning(ChatData)
        )
    elif runtime_config.db_is_mysql:
        stmt = (
            sqlalchemy.dialects.mysql.insert(ChatData)
            .values(
                id=chat_id,
                title=chat.title,
                username=chat.username,
            )
            .on_duplicate_key_update(
                title=chat.title,
                username=chat.username,
            )
            .returning(ChatData)
        )
    elif runtime_config.db_is_sqlite:
        stmt = (
            sqlalchemy.dialects.sqlite.insert(ChatData)
            .values(
                id=chat_id,
                title=chat.title,
                username=chat.username,
            )
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "title": chat.title,
                    "username": chat.username,
                },
            )
            .returning(ChatData)
        )
    else:
        chat_data = await session.get(ChatData, chat_id)
        if chat_data is None:
            chat_data = ChatData(
                id=chat_id,
                title=chat.title,
                username=chat.username,
            )
            session.add(chat_data)
        else:
            chat_data.title = chat.title or ""
            chat_data.username = chat.username
        _upsert_chat_cache[chat_id] = cache_data
        return chat_data

    result = await session.execute(stmt)
    chat_data = result.scalars().first()
    if chat_data is not None:
        _upsert_chat_cache[chat_id] = cache_data
        return chat_data

    data = await session.get(ChatData, chat_id)
    assert data is not None
    _upsert_chat_cache[chat_id] = cache_data
    return data


@with_session
async def get_chat_by_id(
    chat_id: int, session: AsyncSession | None = None
) -> ChatData | None:
    assert session is not None

    chat_data = await session.get(ChatData, chat_id)
    if chat_data is None:
        return None
    return chat_data


async def get_chat_config(chat: int | ChatData | Chat) -> ChatConfig:
    if isinstance(chat, ChatData):
        config = chat.chat_config
        await memttlcache.set(
            f"{_CHAT_CONFIG_CACHE_PREFIX}{chat.id}", config, _CHAT_CONFIG_CACHE_TTL
        )
        return config

    chat_id: int
    if isinstance(chat, Chat):
        if chat.id is None:
            raise ValueError("chat.id must not be None")
        chat_id = chat.id
    elif isinstance(chat, int):
        chat_id = chat
    else:
        raise TypeError("chat must be int, ChatData or Chat")

    cached = await memttlcache.get(f"{_CHAT_CONFIG_CACHE_PREFIX}{chat_id}")
    if cached is not None:
        return cached

    chat_data: ChatData | None = None
    if isinstance(chat, Chat):
        chat_data = await upsert_chat(chat)
    else:
        chat_data = await get_chat_by_id(chat_id)

    if chat_data is None:
        raise ValueError("Chat not found")

    config = chat_data.chat_config
    await memttlcache.set(
        f"{_CHAT_CONFIG_CACHE_PREFIX}{chat_id}", config, _CHAT_CONFIG_CACHE_TTL
    )
    return config


@with_tx
async def update_chat_config(
    chat: int | ChatData | Chat, config: ChatConfig, session: AsyncSession | None = None
) -> ChatConfig:
    assert session is not None

    chat_id = 0
    if isinstance(chat, ChatData):
        chat_id = chat.id
    elif isinstance(chat, Chat):
        if chat.id is None:
            raise ValueError("chat.id must not be None")
        chat_id = chat.id
    elif isinstance(chat, int):
        chat_id = chat
    else:
        raise TypeError("chat must be int, ChatData or Chat")

    chat_data = await session.get(ChatData, chat_id)
    if chat_data is None:
        if isinstance(chat, Chat):
            chat_data = ChatData(
                id=chat_id,
                title=chat.title,
                username=chat.username,
            )
            session.add(chat_data)
            await session.flush()
        else:
            raise ValueError(f"Chat with id {chat_id} not found")
    chat_data.chat_config = config

    # 立即更新缓存，使新配置对后续请求即时生效
    await memttlcache.set(
        f"{_CHAT_CONFIG_CACHE_PREFIX}{chat_id}", config, _CHAT_CONFIG_CACHE_TTL
    )

    return chat_data.chat_config


@with_session
async def get_chats_page(
    page: int = 1,
    size: int = pagination.DEFAULT_PAGE_SIZE,
    query: str = "",
    session: AsyncSession | None = None,
) -> pagination.Page[ChatData]:
    """List groups for the developer panel, newest first."""
    assert session is not None

    page, size = pagination.normalize_page(page, size)
    conditions = []
    query = query.strip()
    if query:
        wanted_id = pagination.parse_id_query(query)
        if wanted_id is not None:
            conditions.append(ChatData.id == wanted_id)
        else:
            conditions.append(
                sqlalchemy.or_(
                    pagination.text_match(ChatData.title, query),
                    pagination.text_match(ChatData.username, query),
                )
            )

    total_stmt = sqlalchemy.select(sqlalchemy.func.count()).select_from(ChatData)
    if conditions:
        total_stmt = total_stmt.where(*conditions)
    total = (await session.execute(total_stmt)).scalar() or 0

    stmt = sqlalchemy.select(ChatData)
    if conditions:
        stmt = stmt.where(*conditions)
    stmt = (
        stmt.order_by(ChatData.created_at.desc(), ChatData.id.desc())
        .offset(pagination.offset_for(page, size))
        .limit(size)
    )
    items = (await session.execute(stmt)).scalars().all()
    return pagination.Page(items=items, total=total, page=page, size=size)


@with_session
async def count_chat_members(chat_id: int, session: AsyncSession | None = None) -> int:
    """Count members the bot knows about, which is what the panel can act on.

    This is the association count, not Telegram's member count: the two differ
    until /syncmembers runs.
    """
    assert session is not None

    stmt = (
        sqlalchemy.select(sqlalchemy.func.count())
        .select_from(UserChatAssociation)
        .where(UserChatAssociation.chat_id == chat_id)
    )
    return (await session.execute(stmt)).scalar() or 0


@with_tx
async def delete_chat(chat_id: int, session: AsyncSession | None = None) -> bool:
    """Remove a group and its cascaded rows. Returns False when absent."""
    assert session is not None

    chat_data = await session.get(ChatData, chat_id)
    if chat_data is None:
        return False
    # The user_chat_association join rows reference chat_data with a RESTRICT
    # constraint in the database, and the members relationship is noload, so
    # clear them explicitly before deleting the chat row.
    await session.execute(
        sqlalchemy.delete(UserChatAssociation).where(
            UserChatAssociation.chat_id == chat_id
        )
    )
    await session.delete(chat_data)
    _upsert_chat_cache.pop(chat_id, None)
    await memttlcache.delete(f"{_CHAT_CONFIG_CACHE_PREFIX}{chat_id}")
    return True
