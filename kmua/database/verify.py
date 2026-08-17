"""新成员验证会话存储。

会话由 `kmua.plugins.verify.verify` 插件创建、作答、删除; 本模块只负责持久化。
表无 FK(同 `chat_policy` 先例): sweep 兜底清理孤儿行, 聊天被删不级联。
"""

from __future__ import annotations

import time

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from kmua.database.db import with_session, with_tx
from kmua.database.models import VerificationMember, VerificationSession


@with_tx
async def create_verification_session(
    session_row: VerificationSession, session: AsyncSession | None = None
) -> VerificationSession:
    """持久化一条新会话, 返回带自增 id 的对象。"""
    assert session is not None
    session.add(session_row)
    await session.flush()
    return session_row


@with_tx
async def update_verification_session(
    session_row: VerificationSession, session: AsyncSession | None = None
) -> None:
    """持久化会话的修改(payload/attempts_left/challenge_message_id)。

    `session_row` 通常是上个事务的游离对象, 用 merge 保证修改被检出并写入。
    """
    assert session is not None
    await session.merge(session_row)
    await session.flush()


@with_session
async def get_verification_session(
    session_id: int, session: AsyncSession | None = None
) -> VerificationSession | None:
    assert session is not None
    return await session.get(VerificationSession, session_id)


@with_tx
async def delete_verification_session(
    session_id: int, session: AsyncSession | None = None
) -> None:
    assert session is not None
    row = await session.get(VerificationSession, session_id)
    if row is not None:
        await session.delete(row)
        await session.flush()


@with_tx
async def delete_verification_sessions_for_user(
    chat_id: int, user_id: int, session: AsyncSession | None = None
) -> None:
    """删除某群某用户的全部会话(用户退群/被移除时调用)。"""
    assert session is not None
    stmt = delete(VerificationSession).where(
        VerificationSession.chat_id == chat_id,
        VerificationSession.user_id == user_id,
    )
    await session.execute(stmt)
    await session.flush()


@with_tx
async def mark_user_verified(
    chat_id: int, user_id: int, session: AsyncSession | None = None
) -> None:
    """记录用户在该群已通过验证(first_message 策略用); 重复记录静默合并。"""
    assert session is not None
    await session.merge(VerificationMember(chat_id=chat_id, user_id=user_id))
    await session.flush()


_VERIFIED_CACHE_TTL = 300.0  # 已验证标记只增不删, 缓存安全
_VERIFIED_CACHE_MAX = 100_000
_verified_cache: dict[str, tuple[float, bool]] = {}


def _verified_cache_get(key: str) -> bool | None:
    """读缓存; 返回 None 表示未命中或已过期"""
    entry = _verified_cache.get(key)
    if entry is None:
        return None
    stamp, value = entry
    if time.monotonic() - stamp >= _VERIFIED_CACHE_TTL:
        return None
    return value


def _verified_cache_set(key: str, value: bool) -> None:
    if len(_verified_cache) >= _VERIFIED_CACHE_MAX:
        now = time.monotonic()
        for k, (stamp, _) in list(_verified_cache.items()):
            if now - stamp >= _VERIFIED_CACHE_TTL:
                del _verified_cache[k]
    _verified_cache[key] = (time.monotonic(), value)


@with_session
async def is_user_verified(
    chat_id: int, user_id: int, session: AsyncSession | None = None
) -> bool:
    """已验证标记(进程内 TTL 缓存); 未验证不缓存, 保证新用户立刻触发验证。"""
    assert session is not None
    cache_key = f"verified:{chat_id}:{user_id}"
    cached = _verified_cache_get(cache_key)
    if cached is not None:
        return cached
    row = await session.get(VerificationMember, (chat_id, user_id))
    if row is None:
        return False
    _verified_cache_set(cache_key, True)
    return True


@with_session
async def get_all_verification_sessions(
    session: AsyncSession | None = None,
) -> list[VerificationSession]:
    """全表读取, sweep 与启动恢复用。"""
    assert session is not None
    result = await session.execute(select(VerificationSession))
    return list(result.scalars().all())


__all__ = [
    "create_verification_session",
    "is_user_verified",
    "mark_user_verified",
    "delete_verification_session",
    "delete_verification_sessions_for_user",
    "get_all_verification_sessions",
    "get_verification_session",
    "update_verification_session",
]
