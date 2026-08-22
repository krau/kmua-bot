import logging
import sys
from datetime import timedelta

from loguru import logger

from kmua.config import app_config


class InterceptHandler(logging.Handler):
    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


logger.remove()

logger.add(
    "logs/kmua.log",
    rotation="04:00",
    enqueue=True,
    encoding="utf-8",
    level="TRACE",
    retention=timedelta(days=app_config.log_retention_days),
)

logger.add(sys.stdout, level=app_config.log_level, enqueue=True)

logging.basicConfig(
    handlers=[InterceptHandler()],
    level=logging.NOTSET,
    force=True,
)

__all__ = ["logger"]
