from .db import Base, engine
from .model import (
    ChatData,  # noqa: F401
    Quote,  # noqa: F401
    UserData,  # noqa: F401
    UserChatAssociation,  # noqa: F401
)

from ..config.config import data_dir

if not data_dir.exists():
    data_dir.mkdir()
Base.metadata.create_all(bind=engine)