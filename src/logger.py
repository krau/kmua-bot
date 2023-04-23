from loguru import logger

logger.add(
    "logs/kmua.log",
    rotation="04:00",
    compression="zip",
    enqueue=True,
    encoding="utf-8",
    level="DEBUG",
)
