from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from kmua.config import settings

engine = create_engine(settings.DB_URL)
_session = scoped_session(sessionmaker(autoflush=False, bind=engine))
_db = _session()


def commit():
    try:
        _db.commit()
    except Exception as err:
        _db.rollback()
        raise err


def close():
    _db.close()
