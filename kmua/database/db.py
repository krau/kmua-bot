import contextlib
from asyncio import current_task
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    async_scoped_session,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.asyncio.session import AsyncSession

from kmua import i18n
from kmua.config import app_config
from kmua.logger import logger

from .models import Base

engine = create_async_engine(app_config.db_url, echo=False, future=True)

AsyncSessionFactory = async_sessionmaker(
    engine,
    autoflush=False,
    expire_on_commit=False,
)
async_session = async_scoped_session(AsyncSessionFactory, scopefunc=current_task)


async def init_db() -> None:
    logger.info(i18n.t("log.db_initing", locale=app_config.lang))
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
