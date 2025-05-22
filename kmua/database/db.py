from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from kmua import i18n
from kmua.config import app_config
from kmua.logger import logger

from .models import Base

engine = create_async_engine(app_config.db_url, echo=True, future=True)

# expire_on_commit=False will prevent attributes from being expired
# after commit.
AsyncSessionFactory = async_sessionmaker(
    engine,
    autoflush=False,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator:
    async with AsyncSessionFactory() as session:
        try:
            yield session
        except Exception as e:
            raise


async def init_db() -> None:
    logger.info(i18n.t("log.db_initing", locale=app_config.lang))
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
