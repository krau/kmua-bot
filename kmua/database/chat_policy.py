"""Operator-controlled per-chat policy.

These are decisions the bot's operator makes about individual chats, as opposed to
`ChatConfig`, which the chat's own admins edit. Keeping them apart matters: the group
settings page saves that document wholesale, so an operator-only flag stored there
would be overwritten by the next group-admin save.

The agent whitelist is the first flag. It gates every agent entry point through
`is_chat_allowed`, which is synchronous and called from message filters that cannot
await - so the flag is mirrored in a module-level set for those readers. Every write
here updates the mirror in the same call, which is what makes a panel edit take effect
on the next message with no expiry to wait out.

Adding a second flag means adding a field to `ChatPolicy` and a getter here. It does
not mean another table, and it does not mean another migration.
"""

from __future__ import annotations

import sqlalchemy
from sqlalchemy.ext.asyncio import AsyncSession

from kmua.logger import logger

from .db import with_session, with_tx
from .models import ChatData, ChatPolicy, ChatPolicyData

# Mirrors the chat ids whose policy has `agent_allowed` set. `None` means "not loaded
# yet", which is distinct from "loaded and empty" - the difference decides whether a
# synchronous reader may trust it.
_agent_cache: set[int] | None = None


def agent_allowed_cache() -> set[int] | None:
    """The mirrored id set, or None when it has not been loaded yet."""
    return _agent_cache


def _set_agent_cache(chat_ids: set[int]) -> None:
    global _agent_cache
    _agent_cache = chat_ids


def _set_agent_cache_unloaded() -> None:
    """Return the mirror to its pre-startup state. Used by tests."""
    global _agent_cache
    _agent_cache = None


def _mirror(chat_id: int, enabled: bool) -> None:
    if _agent_cache is None:
        return
    if enabled:
        _agent_cache.add(chat_id)
    else:
        _agent_cache.discard(chat_id)


@with_session
async def load_agent_allowed_chats(session: AsyncSession | None = None) -> set[int]:
    """Read every chat with the agent flag set, and refresh the mirror.

    Filtering happens in Python rather than in SQL: the flag lives in a JSON column and
    the extraction syntax differs per backend, while this table only holds rows an
    operator has explicitly touched - a few dozen at most.
    """
    assert session is not None

    result = await session.execute(sqlalchemy.select(ChatPolicyData))
    enabled = {
        row.chat_id for row in result.scalars().all() if row.chat_policy.agent_allowed
    }
    _set_agent_cache(enabled)
    return enabled


@with_session
async def get_chat_policies(
    session: AsyncSession | None = None,
) -> list[tuple[ChatPolicyData, str | None]]:
    """List policy rows with the chat's current title, newest first.

    The joined title comes from `chat_data` and wins over the stored copy, which can be
    stale or absent. A LEFT JOIN because a row may name a chat the bot has not seen.
    """
    assert session is not None

    stmt = (
        sqlalchemy.select(ChatPolicyData, ChatData.title)
        .outerjoin(ChatData, ChatData.id == ChatPolicyData.chat_id)
        .order_by(ChatPolicyData.created_at.desc())
    )
    result = await session.execute(stmt)
    return [(row, title) for row, title in result.all()]


@with_session
async def get_chat_policy(
    chat_id: int, session: AsyncSession | None = None
) -> ChatPolicy:
    """One chat's policy, at defaults when no row exists."""
    assert session is not None

    row = await session.get(ChatPolicyData, chat_id)
    return row.chat_policy if row else ChatPolicy()


@with_tx
async def set_chat_policy(
    chat_id: int,
    policy: ChatPolicy,
    *,
    updated_by: int | None = None,
    note: str | None = None,
    session: AsyncSession | None = None,
) -> tuple[ChatPolicy, ChatPolicy]:
    """Write a chat's policy, creating the row if needed.

    Returns `(old, new)` so the caller can record exactly what changed rather than
    re-reading and guessing.
    """
    assert session is not None

    row = await session.get(ChatPolicyData, chat_id)
    if row is None:
        chat = await session.get(ChatData, chat_id)
        row = ChatPolicyData(
            chat_id=chat_id,
            chat_title=chat.title if chat else None,
        )
        session.add(row)
        old = ChatPolicy()
    else:
        old = row.chat_policy

    row.chat_policy = policy
    row.updated_by = updated_by
    if note is not None:
        row.note = note or None
    await session.flush()

    _mirror(chat_id, policy.agent_allowed)
    logger.info(f"chat policy: {chat_id} -> {policy.to_dict()}")
    return old, policy


@with_tx
async def delete_chat_policy(chat_id: int, session: AsyncSession | None = None) -> bool:
    """Drop a chat's policy row, returning it to defaults. False when absent."""
    assert session is not None

    row = await session.get(ChatPolicyData, chat_id)
    if row is None:
        return False

    await session.delete(row)
    await session.flush()

    _mirror(chat_id, False)
    logger.info(f"chat policy: {chat_id} removed")
    return True


@with_tx
async def seed_agent_allowed_chats(
    chat_ids: list[int], session: AsyncSession | None = None
) -> int:
    """Turn a config-supplied whitelist into policy rows.

    Used once at startup to carry a `settings.toml` list over. Only inserts rows that
    do not exist, and the caller only runs it while the table is empty, so an id
    removed in the panel is not resurrected on the next restart.
    """
    assert session is not None

    if not chat_ids:
        return 0

    result = await session.execute(sqlalchemy.select(ChatPolicyData.chat_id))
    known = set(result.scalars().all())
    missing = [cid for cid in dict.fromkeys(chat_ids) if cid not in known]
    if not missing:
        return 0

    for chat_id in missing:
        chat = await session.get(ChatData, chat_id)
        row = ChatPolicyData(chat_id=chat_id, chat_title=chat.title if chat else None)
        row.chat_policy = ChatPolicy(agent_allowed=True)
        session.add(row)
    await session.flush()

    if _agent_cache is not None:
        _agent_cache.update(missing)
    return len(missing)


@with_session
async def count_chat_policies(session: AsyncSession | None = None) -> int:
    assert session is not None

    stmt = sqlalchemy.select(sqlalchemy.func.count()).select_from(ChatPolicyData)
    result = await session.execute(stmt)
    return result.scalar() or 0


__all__ = [
    "agent_allowed_cache",
    "count_chat_policies",
    "delete_chat_policy",
    "get_chat_policies",
    "get_chat_policy",
    "load_agent_allowed_chats",
    "seed_agent_allowed_chats",
    "set_chat_policy",
]
