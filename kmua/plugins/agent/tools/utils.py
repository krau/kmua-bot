import datetime

from kmua.logger import logger


def get_current_time() -> datetime.datetime:
    logger.debug("get current time")
    return datetime.datetime.now()
