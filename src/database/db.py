from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session, declarative_base
from ..config.config import settings

engine = create_engine(settings.DB_URL)
_session = scoped_session(sessionmaker(autoflush=False, bind=engine))
db = _session()
Base = declarative_base()
