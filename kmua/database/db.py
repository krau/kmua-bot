from contextlib import asynccontextmanager
from typing import AsyncGenerator

import alembic
import alembic.config
import pathlib
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from kmua import i18n
from kmua.config import app_config
from kmua.logger import logger

from .models import Base

try:
    logger.debug("migrating database...")
    _alembic_config = alembic.config.Config(
        pathlib.Path(__file__).resolve().parent.parent.parent / "alembic.ini"
    )
    _alembic_config.set_main_option("sqlalchemy.url", app_config.db_url)
    alembic.command.upgrade(_alembic_config, "head")
    logger.debug("migrated database")
except Exception as err:
    logger.warning(f"migrate database failed: {err}")
    logger.warning(
        "if you are running the bot for the first time, or your database does not need to be migrated, ignore this warning"
    )


engine = create_async_engine(app_config.db_url, echo=app_config.debug, future=True)

AsyncSessionFactory = async_sessionmaker(
    bind=engine, autoflush=False, expire_on_commit=False
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


async def init_db() -> None:
    logger.info(i18n.t("log.db_initing", locale=app_config.lang))
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    logger.info(i18n.t("log.db_closing", locale=app_config.lang))
    await engine.dispose()
