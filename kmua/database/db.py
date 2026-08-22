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

    优先使用配置的 jobstore_db_url，否则从 db_url 推断同步驱动版本
    """
    if app_config.jobstore_db_url:
        return app_config.jobstore_db_url

    # 从异步 URL 推断同步版本
    url = app_config.db_url
    replacements = [
        ("+aiosqlite", ""),  # sqlite+aiosqlite -> sqlite
        ("+asyncpg", ""),  # postgresql+asyncpg -> postgresql
        ("+aiomysql", ""),  # mysql+aiomysql -> mysql
    ]
    for async_driver, sync_driver in replacements:
        url = url.replace(async_driver, sync_driver)
    return url


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


async def close_db() -> None:
    logger.info(i18n.t("log.db_closing", locale=app_config.lang))
    await engine.dispose()
