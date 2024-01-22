from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from kmua.config import data_dir, settings
from kmua.logger import logger
from kmua.models.models import Base

engine = create_engine(settings.DB_URL)
_session = scoped_session(sessionmaker(autoflush=False, bind=engine))
_db = _session()

if not data_dir.exists():
    data_dir.mkdir()

logger.debug("Connecting to database...")

Base.metadata.create_all(bind=engine)

logger.success("Success connected to database")


def commit():
    try:
        _db.commit()
    except Exception as err:
        _db.rollback()
        raise err


def close():
    _db.close()
