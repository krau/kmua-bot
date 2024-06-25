from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from kmua.config import data_dir, settings
from kmua.logger import logger
from kmua.models.models import Base

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
