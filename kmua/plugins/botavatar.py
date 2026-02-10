import io
import random

import httpx
from pyrogram import filters
from pyrogram.client import Client
from pyrogram.types import InputChatPhotoStatic, Message

from kmua import database, i18n
from kmua.config import app_config
from kmua.logger import logger


@Client.on_message(filters.command("randmyavatar"), group=0)
async def randmyavatar_command(client: Client, message: Message):
    """
    管理员命令：立刻更换 bot 头像
    """
    user = message.from_user
    if user is None:
        return

    # 权限检查
    db_user = await database.get_user_by_id(user.id)
    if db_user and not db_user.is_bot_global_admin and user.id not in app_config.owners:
        return
    elif not db_user and user.id not in app_config.owners:
        return

    # 获取用户语言
    user_config = await database.get_user_config(user.id)
    lang = user_config.lang

    # 检查服务是否可用
    from kmua.services import aniobjcut, manyacg

    if not manyacg.manyacg_client or not aniobjcut.aniobjcut_client:
        await message.reply_text(
            i18n.t("bot.msg.randmyavatar.service_unavailable", locale=lang)
        )
        return

    # 发送处理中的消息
    status_msg = await message.reply_text(
        i18n.t("bot.msg.randmyavatar.processing", locale=lang)
    )

    try:
        # 获取随机图片
        resp = await manyacg.manyacg_client.random_artwork(limit=1, r18=0)
        if resp.status != 200 or not resp.data:
            await status_msg.edit_text(
                i18n.t("bot.msg.randmyavatar.fetch_failed", locale=lang)
            )
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

        # 更新头像
        await client.set_profile_photo(
            InputChatPhotoStatic(io.BytesIO(avatar)), is_public=True
        )

        # 成功消息
        await status_msg.edit_text(
            i18n.t("bot.msg.randmyavatar.success", locale=lang).format(
                title=artwork.title, url=artwork.source_url
            )
        )

        logger.info(
            f"bot avatar changed by user {user.id}, artwork: {artwork.title} ({artwork.source_url})"
        )

    except Exception as e:
        await status_msg.edit_text(
            i18n.t("bot.msg.randmyavatar.failed", locale=lang).format(error=str(e))
        )
        logger.exception(f"failed to change bot avatar by command: {e}")
