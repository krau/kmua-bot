import os
import platform
import time
from pathlib import Path

import psutil

import kmua.dao as dao
from kmua.config import data_dir, settings

_database_path = Path(
    data_dir / settings.get("db_url", "sqlite:///./data/kmua.db").split("/")[-1]
)


def get_bot_status() -> str:
    db_status = f"""
Database Status:
    - Users: {dao.get_all_users_count()}
    - Chats: {dao.get_all_chats_count()}
    - Quotes: {dao.get_all_quotes_count()}
    - Associations: {dao.get_all_associations_count()}
    """
    if settings.get("db_url").startswith("sqlite"):
        db_status += f"- Size: {_database_path.stat().st_size / 1024 / 1024:.2f} MB"
    db_status += "\n"
    pid = os.getpid()
    p = psutil.Process(pid)
    process_status = f"""
Process Status:
    - Memory: {p.memory_full_info().rss / 1024 / 1024:.2f} MB
    - Uptime: {(time.time() - p.create_time()) / 60 / 60:.2f} hours
    - Python: {platform.python_version()}
    """
    system_status = f"""
System Status:
    - System: {platform.system()} {platform.release()}
    - Total Memory: {psutil.virtual_memory().total / 1024 / 1024:.2f} MB
    - Time: {time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())}
    """
    return db_status + process_status + system_status
