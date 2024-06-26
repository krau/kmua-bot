import pathlib

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

import alembic
import alembic.command
import alembic.config
from kmua.config import data_dir, settings
from kmua.logger import logger
from kmua.models.models import Base

try:
    logger.debug("migrating database...")
    _alembic_config = alembic.config.Config(
        pathlib.Path(__file__).resolve().parent.parent.parent / "alembic.ini"
    )
    alembic.command.upgrade(_alembic_config, "head")
except Exception as err:
    logger.warning(f"migrate database failed: {err}")
    logger.warning(
        "if you are running the bot for the first time, or your database does not need to be migrated, ignore this warning"
    )

engine = create_engine(settings.get("db_url", "sqlite:///./data/kmua.db"))
_session = scoped_session(sessionmaker(autoflush=False, bind=engine))
_db = _session()

data_dir.mkdir(exist_ok=True)

logger.debug("Connecting to database...")

Base.metadata.create_all(bind=engine)

logger.debug("Database connected")


def commit():
    try:
        _db.commit()
    except Exception as err:
        _db.rollback()
        raise err


def close():
    _db.close()
