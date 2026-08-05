"""Agent-persisted file records (kmua.plugins.agent persistent_file tool).

One row per (chat, name): the document message the bot sent to the chat and
the download credential. Scope is chat-wide — group chats share their files,
private chats are user-scoped.
"""

from __future__ import annotations

import sqlalchemy
from sqlalchemy.ext.asyncio import AsyncSession

from kmua.database.db import with_session, with_tx
from kmua.database.models import AgentPersistentFile


def _upsert_stmt(values: dict, dialect: str):
    """A dialect-correct atomic upsert statement for (chat_id, name).

    SQLite and PostgreSQL use ON CONFLICT DO UPDATE, MySQL uses ON DUP
    KEY UPDATE; anything else is rejected rather than guessed, so a
    misconfigured backend fails loudly before any document is sent.
    """
    if dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        stmt = sqlite_insert(AgentPersistentFile).values(**values)
        return stmt.on_conflict_do_update(
            index_elements=["chat_id", "name"],
            set_={
                "description": values["description"],
                "tg_message_id": values["tg_message_id"],
                "file_id": values["file_id"],
                "file_unique_id": values["file_unique_id"],
                "file_name": values["file_name"],
                "mime_type": values["mime_type"],
                "file_size": values["file_size"],
                "updated_at": sqlalchemy.func.now(),
            },
        )
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = pg_insert(AgentPersistentFile).values(**values)
        return stmt.on_conflict_do_update(
            index_elements=["chat_id", "name"],
            set_={
                "description": values["description"],
                "tg_message_id": values["tg_message_id"],
                "file_id": values["file_id"],
                "file_unique_id": values["file_unique_id"],
                "file_name": values["file_name"],
                "mime_type": values["mime_type"],
                "file_size": values["file_size"],
                "updated_at": sqlalchemy.func.now(),
            },
        )
    if dialect == "mysql":
        from sqlalchemy.dialects.mysql import insert as mysql_insert

        stmt = mysql_insert(AgentPersistentFile).values(**values)
        return stmt.on_duplicate_key_update(
            description=values["description"],
            tg_message_id=values["tg_message_id"],
            file_id=values["file_id"],
            file_unique_id=values["file_unique_id"],
            file_name=values["file_name"],
            mime_type=values["mime_type"],
            file_size=values["file_size"],
            updated_at=sqlalchemy.func.now(),
        )
    raise ValueError(f"Unsupported database dialect for persisted files: {dialect}")


@with_tx
async def upsert_persistent_file(
    chat_id: int,
    name: str,
    description: str | None,
    tg_message_id: int,
    file_id: str,
    file_unique_id: str,
    file_name: str | None,
    mime_type: str | None,
    file_size: int | None,
    session: AsyncSession | None = None,
) -> AgentPersistentFile:
    """Insert a record or overwrite the existing one for (chat_id, name).

    Atomic ON CONFLICT upsert (SQLite and PostgreSQL), so two concurrent
    first writes for the same (chat_id, name) cannot race into a unique
    violation.
    """
    assert session is not None, "Session must be provided"
    values = {
        "chat_id": chat_id,
        "name": name,
        "description": description,
        "tg_message_id": tg_message_id,
        "file_id": file_id,
        "file_unique_id": file_unique_id,
        "file_name": file_name,
        "mime_type": mime_type,
        "file_size": file_size,
    }
    stmt = _upsert_stmt(values, session.get_bind().dialect.name)
    await session.execute(stmt)
    await session.flush()
    record = (
        await session.execute(
            sqlalchemy.select(AgentPersistentFile).where(
                AgentPersistentFile.chat_id == chat_id,
                AgentPersistentFile.name == name,
            )
        )
    ).scalar_one()
    return record


@with_session
async def get_persistent_file(
    chat_id: int, name: str, session: AsyncSession | None = None
) -> AgentPersistentFile | None:
    assert session is not None, "Session must be provided"
    stmt = sqlalchemy.select(AgentPersistentFile).where(
        AgentPersistentFile.chat_id == chat_id,
        AgentPersistentFile.name == name,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


@with_session
async def list_persistent_files(
    chat_id: int, session: AsyncSession | None = None
) -> list[AgentPersistentFile]:
    assert session is not None, "Session must be provided"
    stmt = (
        sqlalchemy.select(AgentPersistentFile)
        .where(AgentPersistentFile.chat_id == chat_id)
        .order_by(AgentPersistentFile.name)
    )
    return list((await session.execute(stmt)).scalars())


@with_tx
async def delete_persistent_file(
    chat_id: int, name: str, session: AsyncSession | None = None
) -> bool:
    """Remove one record; the Telegram message stays in chat history."""
    assert session is not None, "Session must be provided"
    record = await get_persistent_file(chat_id, name, session)
    if record is None:
        return False
    await session.delete(record)
    await session.flush()
    return True


@with_tx
async def delete_all_persistent_files(
    session: AsyncSession | None = None,
) -> int:
    """Remove every record (owner-level session wipe); messages stay."""
    assert session is not None, "Session must be provided"
    result = await session.execute(sqlalchemy.delete(AgentPersistentFile))
    await session.flush()
    return result.rowcount or 0  # type: ignore[attr-defined]
