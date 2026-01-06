from kmua import common, database, enums
from kmua.config import app_config
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


async def publish_reflection():
    """发布 agent 反思贴文"""
    if not app_config.agent or not app_config.fans_channel:
        return
    
    try:
        from kmua.bot.client import client
        from kmua.plugins.agent.reflection import publish_reflection_post
        
        logger.info("Publishing reflection post...")
        success = await publish_reflection_post(client)
        if success:
            logger.success("Reflection post published successfully")
        else:
            logger.warning("Failed to publish reflection post")
    except Exception as e:
        logger.error(f"Error in publish_reflection job: {e}")
