from kmua.config import settings
from kmua.logger import logger

redis_client = None
_REDIS_URL = settings.get("redis_url")

if _REDIS_URL:
    logger.debug("initing redis client...")
    import redis

    try:
        redis_client = redis.from_url(_REDIS_URL)
        logger.debug(f"redis client: {redis_client.ping()}")
    except Exception as e:
        logger.error(f"redis client error: {e.__class__.__name__}: {e}")
        exit(1)
