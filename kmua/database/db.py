import inspect
import pathlib
from contextlib import asynccontextmanager
from functools import wraps
from typing import AsyncGenerator, Awaitable, Callable, ParamSpec, TypeVar

import alembic.command
import alembic.config
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from kmua import i18n
from kmua.config import app_config
from kmua.logger import logger

from .models import Base

engine = create_async_engine(app_config.db_url, echo=app_config.debug, future=True)

AsyncSessionFactory = async_sessionmaker(
    bind=engine, autoflush=True, expire_on_commit=False
)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
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


def with_session(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
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


def with_tx(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
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


async def init_db() -> None:
    logger.info(i18n.t("log.db_initing", locale=app_config.lang))
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    logger.info(i18n.t("log.db_closing", locale=app_config.lang))
    await engine.dispose()
