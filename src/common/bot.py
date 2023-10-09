import os
import time
from pathlib import Path

import psutil

from ..config import data_dir, settings
from ..dao.association import get_all_associations_count
from ..dao.chat import get_all_chats_count
from ..dao.quote import get_all_quotes_count
from ..dao.user import get_all_users_count

_database_path = Path(
    data_dir / settings.get("db_url", "sqlite:///./data/kmua.db").split("/")[-1]
)


def get_bot_status() -> str:
    db_status = f"""
Database Status:
    - Users: {get_all_users_count()}
    - Chats: {get_all_chats_count()}
    - Quotes: {get_all_quotes_count()}
    - Associations: {get_all_associations_count()}
    - Size: {_database_path.stat().st_size / 1024 / 1024:.2f} MB
    """
    pid = os.getpid()
    p = psutil.Process(pid)
    process_status = f"""
Process Status:
    - Memory: {p.memory_info().rss / 1024 / 1024:.2f} MB
    - CPU: {p.cpu_percent()}%
    - Uptime: {(time.time() - p.create_time()) / 60 / 60:.2f} hours
    - PID: {pid}
    - PWD: {os.getcwd()}
    - Python: {psutil.Process().exe()}
    """
    return db_status + process_status
