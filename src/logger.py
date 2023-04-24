from loguru import logger
import sys
from .config.config import settings

logger.remove()
logger.add(
    "logs/kmua.log",
    rotation="04:00",
    compression="zip",
    enqueue=True,
    encoding="utf-8",
    level="TRACE",
)

logger.add(sys.stderr, level=settings.log_level if settings.log_level else "INFO")
