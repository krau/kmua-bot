import sys

from loguru import logger

from .config import settings

logger.remove()
logger.add(
    "logs/kmua.log",
    rotation="04:00",
    enqueue=True,
    encoding="utf-8",
    level="TRACE",
    retention="30 days",
)

logger.add(sys.stdout, level=settings.get("log_level", "INFO"))
