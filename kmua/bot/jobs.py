from kmua import common, database, enums
from kmua.logger import logger


async def cleanup():
    try:
        logger.info("cleaning data")
        await common.memstore.set(enums.GLockKey.CLEANING, True)
        await database.cleanup_waifu_data()
        # await database.cleanup_user_avatar()
        # common.cleanup_avatar_cache()
    finally:
        logger.info("clean data done")
        await common.memstore.delete(enums.GLockKey.CLEANING)