import asyncio
import struct
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
import sqlite_vec

from kmua.config import app_config
from kmua.logger import logger

_DB_PATH: Path | None = None
_INITIALIZED = False

# 批量处理配置
_EVICT_BATCH_SIZE = 100  # 每次清理的最大记录数


def _db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        _DB_PATH = Path(app_config.agent_sticker_db_path)
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return _DB_PATH


@asynccontextmanager
async def _connect() -> AsyncGenerator[aiosqlite.Connection]:
    async with aiosqlite.connect(_db_path()) as db:
        await db.enable_load_extension(True)
        await db.load_extension(sqlite_vec.loadable_path())
        await db.enable_load_extension(False)
        yield db


async def init() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    dims = app_config.agent_sticker_embed_dimensions
    async with _connect() as db:
        await db.executescript(f"""
            CREATE TABLE IF NOT EXISTS stickers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_unique_id TEXT NOT NULL,
                file_id TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                description TEXT,
                last_seen INTEGER NOT NULL,
                UNIQUE(file_unique_id, chat_id)
            );
            CREATE INDEX IF NOT EXISTS idx_stickers_chat ON stickers(chat_id);
            CREATE INDEX IF NOT EXISTS idx_stickers_uid ON stickers(file_unique_id, chat_id);
            CREATE VIRTUAL TABLE IF NOT EXISTS sticker_embeddings
                USING vec0(embedding float[{dims}]);
        """)
        await db.commit()
    _INITIALIZED = True


def _pack(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


async def _lazy_evict(db: aiosqlite.Connection, chat_id: int | None = None) -> None:
    """清理过期贴纸记录，分批处理避免阻塞事件循环。

    智能清理策略：当聊天室的贴纸数量少于配置的阈值时，保留所有贴纸不逐出。
    这确保小群聊不会频繁丢失贴纸记忆。

    Args:
        db: 数据库连接
        chat_id: 可选的聊天室ID，用于检查该聊天室的贴纸数量
    """
    ttl = app_config.agent_sticker_ttl
    if ttl <= 0:
        return

    min_keep = app_config.agent_sticker_min_keep_count

    # 如果指定了 chat_id，检查该聊天室的贴纸总数
    if chat_id is not None and min_keep > 0:
        count_cursor = await db.execute(
            "SELECT COUNT(*) FROM stickers WHERE chat_id = ?", (chat_id,)
        )
        count_row = await count_cursor.fetchone()
        total_count = count_row[0] if count_row else 0

        if total_count < min_keep:
            logger.debug(
                f"sticker_vec: skip eviction for chat {chat_id}, "
                f"total stickers ({total_count}) < threshold ({min_keep})"
            )
            return

    cutoff = int(time.time()) - ttl

    # 构建查询条件
    where_clause = "last_seen < ?"
    params: list = [cutoff, _EVICT_BATCH_SIZE]
    if chat_id is not None:
        where_clause = "last_seen < ? AND chat_id = ?"
        params = [cutoff, chat_id, _EVICT_BATCH_SIZE]

    # 使用 LIMIT 分批查询，避免一次加载过多数据
    rows = await db.execute_fetchall(
        f"SELECT id FROM stickers WHERE {where_clause} LIMIT ?",
        params,
    )
    if not rows:
        return
    expired_ids = [row[0] for row in rows]
    placeholders = ",".join("?" * len(expired_ids))
    await db.execute(
        f"DELETE FROM sticker_embeddings WHERE rowid IN ({placeholders})", expired_ids
    )
    await db.execute(f"DELETE FROM stickers WHERE id IN ({placeholders})", expired_ids)
    await db.commit()
    logger.debug(f"sticker_vec: evicted {len(expired_ids)} expired stickers")

    # 如果清理了满批次的记录，给其他任务一个运行机会
    if len(expired_ids) >= _EVICT_BATCH_SIZE:
        await asyncio.sleep(0)


async def exists(file_unique_id: str, chat_id: int) -> bool:
    async with _connect() as db:
        # 使用 fetchone 更高效，避免不必要的列表转换
        cursor = await db.execute(
            "SELECT 1 FROM stickers WHERE file_unique_id = ? AND chat_id = ? LIMIT 1",
            (file_unique_id, chat_id),
        )
        row = await cursor.fetchone()
        return row is not None


async def upsert(
    file_unique_id: str,
    file_id: str,
    chat_id: int,
    description: str,
    embedding: list[float],
) -> None:
    async with _connect() as db:
        await _lazy_evict(db, chat_id)
        now = int(time.time())
        # 使用 fetchone 替代 execute_fetchall + list，减少阻塞
        cursor = await db.execute(
            "SELECT id FROM stickers WHERE file_unique_id = ? AND chat_id = ? LIMIT 1",
            (file_unique_id, chat_id),
        )
        existing = await cursor.fetchone()
        if existing:
            row_id = existing[0]
            await db.execute(
                "UPDATE stickers SET file_id=?, description=?, last_seen=? WHERE id=?",
                (file_id, description, now, row_id),
            )
            await db.execute(
                "DELETE FROM sticker_embeddings WHERE rowid = ?", (row_id,)
            )
            await db.execute(
                "INSERT INTO sticker_embeddings(rowid, embedding) VALUES (?, ?)",
                (row_id, _pack(embedding)),
            )
        else:
            cur = await db.execute(
                "INSERT INTO stickers(file_unique_id, file_id, chat_id, description, last_seen) "
                "VALUES (?,?,?,?,?)",
                (file_unique_id, file_id, chat_id, description, now),
            )
            row_id = cur.lastrowid
            await db.execute(
                "INSERT INTO sticker_embeddings(rowid, embedding) VALUES (?, ?)",
                (row_id, _pack(embedding)),
            )
        await db.commit()


async def delete(file_unique_id: str, chat_id: int) -> bool:
    """Remove one sticker from a chat's memory store; False when absent."""
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT id FROM stickers WHERE file_unique_id = ? AND chat_id = ? LIMIT 1",
            (file_unique_id, chat_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return False
        row_id = row[0]
        await db.execute("DELETE FROM sticker_embeddings WHERE rowid = ?", (row_id,))
        await db.execute("DELETE FROM stickers WHERE id = ?", (row_id,))
        await db.commit()
        return True


async def touch(file_unique_id: str, chat_id: int) -> None:
    async with _connect() as db:
        await db.execute(
            "UPDATE stickers SET last_seen=? WHERE file_unique_id=? AND chat_id=?",
            (int(time.time()), file_unique_id, chat_id),
        )
        await db.commit()


async def count(chat_id: int) -> int:
    """Return the number of stickers stored for a chat."""
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM stickers WHERE chat_id = ?", (chat_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0


async def search(
    chat_id: int,
    embedding: list[float],
    k: int = 5,
) -> list[tuple[str, str, float]]:
    """Return up to k results as (file_id, description, distance)."""
    async with _connect() as db:
        await _lazy_evict(db, chat_id)
        rows = await db.execute_fetchall(
            """
            SELECT s.file_id, s.description, e.distance
            FROM sticker_embeddings e
            JOIN stickers s ON s.id = e.rowid
            WHERE e.embedding MATCH ? AND k = ?
                  AND e.rowid IN (SELECT id FROM stickers WHERE chat_id = ?)
            ORDER BY e.distance
            """,
            (_pack(embedding), k, chat_id),
        )
        result = []
        for i, r in enumerate(rows):
            if i >= k:
                break
            result.append((r[0], r[1], r[2]))
        return result
