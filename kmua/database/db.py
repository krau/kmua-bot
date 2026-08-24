import inspect
import pathlib
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from functools import wraps
from typing import ParamSpec, TypeVar

import alembic.command
import alembic.config
import sqlalchemy
from sqlalchemy import create_engine, event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from kmua import i18n
from kmua.config import app_config, runtime_config
from kmua.logger import logger

from .models import Base

engine = create_async_engine(app_config.db_url, echo=app_config.debug, future=True)


def _tune_sqlite_pragmas(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


if app_config.db_url.startswith("sqlite"):
    event.listen(engine.sync_engine, "connect", _tune_sqlite_pragmas)


def _get_jobstore_db_url() -> str:
    """获取 APScheduler job store 的数据库 URL

    优先使用配置的 jobstore_db_url，否则使用本地 SQLite 文件。

    The job store is queried with synchronous SQLAlchemy from the event loop
    on every scheduler wakeup. Deriving it from db_url used to put those
    queries on the main database server - over the network for PostgreSQL -
    so one slow query or lock wait froze the whole process. A local file
    keeps every job-store operation sub-millisecond; pending jobs are
    migrated once from the legacy location (see _migrate_legacy_jobstore).
    """
    if app_config.jobstore_db_url:
        return app_config.jobstore_db_url
    return f"sqlite:///{pathlib.Path('data') / 'kmua-jobstore.db'}"


def _legacy_jobstore_url() -> str:
    """Pre-2.x derivation: db_url with the async driver stripped."""
    url = app_config.db_url
    replacements = [
        ("+aiosqlite", ""),  # sqlite+aiosqlite -> sqlite
        ("+asyncpg", ""),  # postgresql+asyncpg -> postgresql
        ("+aiomysql", ""),  # mysql+aiomysql -> mysql
    ]
    for async_driver, sync_driver in replacements:
        url = url.replace(async_driver, sync_driver)
    return url


def _migrate_legacy_jobstore() -> None:
    """Copy pending jobs from the legacy job-store location once.

    Older versions stored APScheduler jobs in the main database server. When
    the local store is empty and the legacy table exists, its rows are
    carried over so scheduled jobs (e.g. agent timers) survive the upgrade.
    Best effort: failures are logged and never block startup.
    """
    legacy_engine = None
    try:
        if app_config.jobstore_db_url:
            return  # user-managed location; nothing to migrate from
        # The job-store table normally appears when APScheduler starts; the
        # migration runs earlier (init_db), so create it with the same schema.
        with sync_engine.begin() as dst:
            dst.execute(
                sqlalchemy.text(
                    "CREATE TABLE IF NOT EXISTS apscheduler_jobs ("
                    "id VARCHAR(191) NOT NULL, "
                    "next_run_time FLOAT(53), "
                    "job_state BLOB NOT NULL, "
                    "PRIMARY KEY (id))"
                )
            )
            existing = dst.execute(
                sqlalchemy.text("SELECT COUNT(*) FROM apscheduler_jobs")
            ).scalar_one()
        if existing > 0:
            return
        legacy_engine = create_engine(_legacy_jobstore_url(), future=True)
        if not sqlalchemy.inspect(legacy_engine).has_table("apscheduler_jobs"):
            return
        with legacy_engine.connect() as src:
            rows = src.execute(
                sqlalchemy.text(
                    "SELECT id, next_run_time, job_state FROM apscheduler_jobs"
                )
            ).fetchall()
        if not rows:
            return
        with sync_engine.begin() as dst:
            dst.execute(
                sqlalchemy.text(
                    "INSERT INTO apscheduler_jobs (id, next_run_time, job_state) "
                    "VALUES (:id, :next_run_time, :job_state)"
                ),
                [
                    {
                        "id": row.id,
                        "next_run_time": row.next_run_time,
                        "job_state": row.job_state,
                    }
                    for row in rows
                ],
            )
        logger.info(f"jobstore migration: carried over {len(rows)} job(s)")
    except Exception as e:
        logger.warning(f"jobstore migration skipped ({e.__class__.__name__}: {e})")
    finally:
        if legacy_engine is not None:
            legacy_engine.dispose()


# Create sync engine for APScheduler job store
# APScheduler 3.x SQLAlchemyJobStore requires sync engine
jobstore_url = _get_jobstore_db_url()
if app_config.jobstore_db_url:
    logger.info("Using configured jobstore_db_url for scheduled jobs")
else:
    logger.debug("Using derived sync URL for job store")
sync_engine = create_engine(jobstore_url, echo=app_config.debug, future=True)


if jobstore_url.startswith("sqlite"):
    event.listen(sync_engine, "connect", _tune_sqlite_pragmas)

AsyncSessionFactory = async_sessionmaker(
    bind=engine, autoflush=True, expire_on_commit=False
)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession]:
    async with AsyncSessionFactory() as ss:
        try:
            yield ss
            await ss.commit()
        except Exception as e:
            logger.exception(f"Session error: {e}")
            await ss.rollback()
            raise
        finally:
            await ss.close()


T = TypeVar("T")
P = ParamSpec("P")


def with_session[**P, T](func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
    sig = inspect.signature(func)

    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        bound = sig.bind_partial(*args, **kwargs)
        bound.apply_defaults()
        if "session" in bound.arguments and isinstance(
            bound.arguments["session"], AsyncSession
        ):
            return await func(*args, **kwargs)
        else:
            async with AsyncSessionFactory() as session:
                return await func(*args, **kwargs, session=session)  # type: ignore

    return wrapper


def with_tx[**P, T](func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
    sig = inspect.signature(func)

    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        bound = sig.bind_partial(*args, **kwargs)
        bound.apply_defaults()

        if "session" in bound.arguments and isinstance(
            bound.arguments["session"], AsyncSession
        ):
            return await func(*args, **kwargs)
        else:
            async with AsyncSessionFactory() as session:
                async with session.begin():
                    return await func(*args, **kwargs, session=session)  # type: ignore

    return wrapper


def migrate_db() -> None:
    logger.debug("migrating database…")

    _alembic_cfg = alembic.config.Config(
        pathlib.Path(__file__).resolve().parent.parent.parent / "alembic.ini"
    )
    _alembic_cfg.set_main_option("sqlalchemy.url", app_config.db_url)
    try:
        alembic.command.upgrade(_alembic_cfg, "head")
    except Exception as e:
        logger.warning(f"Failed to migrate database: {e.__class__.__name__} - {e}")
        logger.warning(
            "if you are running the bot for the first time, or your database does not need to be migrated, ignore this warning"
        )


async def manage_quote_text_index() -> None:
    """
    根据 pg_pgroonga 配置切换 PGroonga 或 pg_trgm 索引。
    """
    if not runtime_config.db_is_postgres:
        return

    logger.debug("Managing quote text search index...")

    async with engine.begin() as conn:
        check_pgroonga_idx = await conn.execute(
            sqlalchemy.text(
                "SELECT 1 FROM pg_indexes WHERE tablename='quotes' AND indexname='idx_quotes_text_pgroonga'"
            )
        )
        has_pgroonga_idx = check_pgroonga_idx.scalar() is not None

        check_gin_idx = await conn.execute(
            sqlalchemy.text(
                "SELECT 1 FROM pg_indexes WHERE tablename='quotes' AND indexname='idx_quotes_text_gin_trgm'"
            )
        )
        has_gin_idx = check_gin_idx.scalar() is not None

        if app_config.pg_pgroonga:
            # 使用 PGroonga
            if has_gin_idx:
                logger.info("Removing pg_trgm index for quotes.text...")
                await conn.execute(
                    sqlalchemy.text("DROP INDEX IF EXISTS idx_quotes_text_gin_trgm")
                )

            if not has_pgroonga_idx:
                logger.info("Creating PGroonga extension and index for quotes.text...")
                # 创建 PGroonga 扩展
                await conn.execute(
                    sqlalchemy.text("CREATE EXTENSION IF NOT EXISTS pgroonga")
                )
                # 创建 PGroonga 索引
                await conn.execute(
                    sqlalchemy.text(
                        "CREATE INDEX idx_quotes_text_pgroonga ON quotes USING pgroonga (text pgroonga_varchar_full_text_search_ops)"
                    )
                )
                logger.success("PGroonga index created for quotes.text")
            else:
                logger.debug("PGroonga index already exists for quotes.text")
        else:
            # pg_trgm
            if has_pgroonga_idx:
                logger.info("Removing PGroonga index for quotes.text...")
                await conn.execute(
                    sqlalchemy.text("DROP INDEX IF EXISTS idx_quotes_text_pgroonga")
                )

            if not has_gin_idx:
                logger.info("Creating pg_trgm extension and index for quotes.text...")
                await conn.execute(
                    sqlalchemy.text("CREATE EXTENSION IF NOT EXISTS pg_trgm")
                )
                await conn.execute(
                    sqlalchemy.text(
                        "CREATE INDEX idx_quotes_text_gin_trgm ON quotes USING gin (text gin_trgm_ops)"
                    )
                )
                logger.success("pg_trgm GIN index created for quotes.text")
            else:
                logger.debug("pg_trgm index already exists for quotes.text")


async def init_db() -> None:
    logger.info(i18n.t("log.db_initing", locale=app_config.lang))
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from .affection import init_affection_histogram

    await init_affection_histogram()
    await manage_quote_text_index()
    _migrate_legacy_jobstore()


async def close_db() -> None:
    logger.info(i18n.t("log.db_closing", locale=app_config.lang))
    await engine.dispose()
