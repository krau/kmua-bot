from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from kmua.models.models import Base
from kmua.config import settings, data_dir
from kmua.logger import logger

engine = create_engine(settings.DB_URL)
_session = scoped_session(sessionmaker(autoflush=False, bind=engine))
_db = _session()

if not data_dir.exists():
    data_dir.mkdir()

logger.debug("Connecting to database...")

Base.metadata.create_all(bind=engine)

logger.info("Success")


def commit():
    try:
        _db.commit()
    except Exception as err:
        _db.rollback()
        raise err


def close():
    _db.close()
