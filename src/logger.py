from loguru import logger
import sys

logger.remove()
logger.add(
    "logs/kmua.log",
    rotation="04:00",
    compression="zip",
    enqueue=True,
    encoding="utf-8",
    level="TRACE",
)

logger.add(sys.stderr, level="INFO")
