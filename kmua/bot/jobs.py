from kmua import common, database, enums, logger
from kmua.logger import logger

from .client import client


async def cleanup():
    try:
        logger.info("cleaning data")
        await common.memstore.set(enums.GLockKey.CLEANING, True)
        await database.cleanup_waifu_data()
    finally:
        logger.info("cleaning data done")
        await common.memstore.delete(enums.GLockKey.CLEANING)
