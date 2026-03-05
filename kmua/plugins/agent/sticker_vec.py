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


async def _lazy_evict(db: aiosqlite.Connection) -> None:
    """清理过期贴纸记录，分批处理避免阻塞事件循环。"""
    ttl = app_config.agent_sticker_ttl
    if ttl <= 0:
        return
    cutoff = int(time.time()) - ttl

    # 使用 LIMIT 分批查询，避免一次加载过多数据
    rows = await db.execute_fetchall(
        "SELECT id FROM stickers WHERE last_seen < ? LIMIT ?",
        (cutoff, _EVICT_BATCH_SIZE),
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
        await _lazy_evict(db)
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


async def touch(file_unique_id: str, chat_id: int) -> None:
    async with _connect() as db:
        await db.execute(
            "UPDATE stickers SET last_seen=? WHERE file_unique_id=? AND chat_id=?",
            (int(time.time()), file_unique_id, chat_id),
        )
        await db.commit()


async def search(
    chat_id: int,
    embedding: list[float],
    k: int = 5,
) -> list[tuple[str, str, float]]:
    """Return up to k results as (file_id, description, distance)."""
    async with _connect() as db:
        await _lazy_evict(db)
        # execute_fetchall 已经返回列表，不需要额外的 list() 转换
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
        # rows 已经是 list，直接切片避免重复列表操作
        return [(r[0], r[1], r[2]) for r in rows[:k]]
