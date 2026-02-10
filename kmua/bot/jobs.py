import io
import random

import httpx
import pyrogram

from kmua import common, database, enums, i18n
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


async def change_bot_avatar():
    """
    定时更换 bot 头像
    使用 manyacg 获取随机图片，aniobjcut 裁切为头像，然后更新 bot profile photo
    """
    from kmua.bot.client import client
    from kmua.services import aniobjcut, manyacg

    if not manyacg.manyacg_client or not aniobjcut.aniobjcut_client:
        logger.warning(i18n.t("log.avatar_change_disabled", locale=app_config.lang))
        return

    try:
        logger.info(i18n.t("log.avatar_changing", locale=app_config.lang))

        # 获取随机图片
        resp = await manyacg.manyacg_client.random_artwork(limit=1, r18=0)
        if resp.status != 200 or not resp.data:
            logger.error(f"failed to get random artwork: {resp.message}")
            return

        artwork = resp.data[0]
        picture = artwork.pictures[random.randint(0, len(artwork.pictures) - 1)]

        # 下载图片
        async with httpx.AsyncClient(timeout=30) as http_client:
            fileresp = await http_client.get(
                f"{app_config.manyacg_api_url}/picture/file/{picture.id}",
            )
            fileresp.raise_for_status()

        # 裁切为头像
        avatar = await aniobjcut.aniobjcut_client.cut_avatar(fileresp.content)

        await client.set_profile_photo(
            pyrogram.types.InputChatPhotoStatic(io.BytesIO(avatar)), is_public=True
        )
        logger.success(
            i18n.t("log.avatar_changed", locale=app_config.lang).format(
                title=artwork.title, url=artwork.source_url
            )
        )

    except Exception as e:
        logger.exception(
            i18n.t("log.avatar_change_failed", locale=app_config.lang).format(
                error=str(e)
            )
        )
