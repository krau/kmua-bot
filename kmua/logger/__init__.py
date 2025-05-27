import sys
from datetime import timedelta

from loguru import logger

from kmua.config import app_config

logger.remove()
logger.add(
    "logs/kmua.log",
    rotation="04:00",
    enqueue=True,
    encoding="utf-8",
    level="TRACE",
    retention=timedelta(days=app_config.log_retention_days),
)

logger.add(sys.stdout, level=app_config.log_level)

__all__ = ["logger"]
