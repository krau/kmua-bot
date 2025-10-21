import html
import io
import random
import re

import httpx
import pyrogram
from pyrogram.client import Client as PyrogramClient

from kmua import common, database, i18n
from kmua.config import app_config
from kmua.logger import logger
from kmua.services import aniobjcut
from kmua.services import manyacg as manyacg_service
from kmua.services.manyacg import manyacg_client

from . import utils

httpx_client = httpx.AsyncClient(
    base_url=app_config.manyacg_api_url, timeout=30, headers={"User-Agent": "KMUA Bot"}
)


@PyrogramClient.on_message(
    pyrogram.filters.regex(
        "|".join([r.pattern for r in manyacg_service.ARTWORK_ALL_REGEX])
    ),
    group=0,
)
async def parse_artwork(client: PyrogramClient, message: pyrogram.types.Message):
    if not app_config.manyacg_api_key or not manyacg_client:
        return
    chat = message.chat
    user = message.from_user or message.sender_chat
    if not user or not user.id:
        return
    if not chat or not chat.type or not chat.id:
        return
    if chat.type in (pyrogram.enums.ChatType.SUPERGROUP, pyrogram.enums.ChatType.GROUP):
        chat_config = await database.get_chat_config(chat.id)
        if not chat_config.parse_artwork_enabled:
            return
        lang = chat_config.lang
    else:
        user_config = await database.get_user_config(user.id)
        lang = user_config.lang
    if not message.matches:
        return
    if not message.text:
        return
    artwork_url = message.matches[0].group()
    if not artwork_url:
        return
    await message.reply_chat_action(pyrogram.enums.ChatAction.UPLOAD_PHOTO)
    if not artwork_url.startswith("http"):
        artwork_url = "https://" + artwork_url
    try:
        resp = await manyacg_client.fetch_artwork(artwork_url)
    except Exception as e:
        logger.error(f"Error fetching artwork: {e}")
        return
    if resp.status_code != 200:
        logger.error(f"fetch_artwork failed: {resp.status_code} {resp.text}")
        return
    artwork: dict = resp.json()
    if artwork["status"] != 200:
        # should not happen
        return
    artwork_title = artwork["data"]["title"]
    artwork_description = artwork["data"]["description"]
    artwork_source_url = artwork["data"]["source_url"]
    artwork_r18 = artwork["data"]["r18"]
    artwork_pictures = artwork["data"]["pictures"][:10]
    artwork_pictures_count = len(artwork["data"]["pictures"])
    cache_id = artwork["data"]["cache_id"]
    try:
        media = []
        caption = f"<a href='{artwork_source_url}'>{html.escape(artwork_title)}</a>\n<blockquote expandable=true>{html.escape(artwork_description)}</blockquote>"
        if artwork_pictures_count > 10:
            caption += i18n.t(
                "bot.msg.manyacg.artwork_pictures_count",
                locale=lang,
            ).format(count=artwork_pictures_count)
            if cache_id:
                caption += f" <a href='https://t.me/{app_config.manyacg_bot}/?start=info_{cache_id}'>{i18n.t('bot.msg.manyacg.seefull', locale=lang)}</a>"
        async with httpx.AsyncClient() as http_client:
            for picture in artwork_pictures:
                photo = await utils.prepare_media(http_client, picture)
                media.append(
                    pyrogram.types.InputMediaPhoto(
                        media=(
                            io.BytesIO(photo)
                            if isinstance(photo, (bytes, bytearray, memoryview))
                            else photo
                        ),
                        has_spoiler=artwork_r18,
                        caption=caption if picture["index"] == 0 else "",
                        parse_mode=pyrogram.enums.ParseMode.HTML,
                    )
                )
        msgs = await message.reply_media_group(media=media)
        for idx, msg in enumerate(msgs):
            image_url = artwork_pictures[idx]["original"]
            if msg.photo is None:
                continue
            photo_file_id = msg.photo.file_id
            await common.memttlcache.set(
                f"artwork:pic_file_id:{image_url}",
                photo_file_id,
                ttl=app_config.cachettl_artwork_pic_file_id,
            )
    except Exception as e:
        logger.error(f"parse_artwork error: {e.__class__.__name__}:{e}")


@PyrogramClient.on_message(pyrogram.filters.command("setu"), group=0)
async def setu_command(client: PyrogramClient, message: pyrogram.types.Message):
    if not manyacg_client:
        return
    chat = message.chat
    user = message.sender_chat or message.from_user
    if not user or not user.id:
        return
    if not chat or not chat.type or not chat.id:
        return
    if chat.type in (pyrogram.enums.ChatType.SUPERGROUP, pyrogram.enums.ChatType.GROUP):
        chat_config = await database.get_chat_config(chat.id)
        if not chat_config.setu_enabled:
            await message.reply(
                i18n.t("bot.msg.manyacg.chat_setu_disabled", locale=chat_config.lang)
            )
            return
        lang = chat_config.lang
    else:
        user_config = await database.get_user_config(user.id)
        lang = user_config.lang
    if await common.memttlcache.get(
        f"setu_cd:{user.id}",
        default=False,
    ):
        await message.reply(
            i18n.t("bot.msg.manyacg.setu_cd", locale=lang),
        )
        return
    await common.memttlcache.set(
        f"setu_cd:{user.id}",
        True,
        ttl=app_config.manyacg_setu_cd,
    )
    try:
        resp = await manyacg_client.random_artwork(limit=1, r18=2)
        if resp.status_code != 200:
            await message.reply(
                i18n.t("bot.msg.manyacg.setu_error", locale=lang),
            )
            return
        artwork: dict = resp.json()["data"][0]
        picture: dict = artwork["pictures"][
            random.randint(0, len(artwork["pictures"]) - 1)
        ]
        detail_link = (
            f"https://t.me/{app_config.manyacg_channel}/{picture['message_id']}"
            if picture.get("message_id")
            else artwork["source_url"]
        )
        await message.reply_photo(
            photo=picture["regular"],
            caption=f"<a href='{artwork['source_url']}'>{html.escape(artwork['title'])}</a>",
            parse_mode=pyrogram.enums.ParseMode.HTML,
            reply_markup=pyrogram.types.InlineKeyboardMarkup(
                [
                    [
                        pyrogram.types.InlineKeyboardButton(
                            text=i18n.t("bot.button.manyacg.detail", locale=lang),
                            url=detail_link,
                        ),
                        pyrogram.types.InlineKeyboardButton(
                            text=i18n.t("bot.button.manyacg.original", locale=lang),
                            url=f"https://t.me/{app_config.manyacg_bot}/?start=file_{picture['id']}",
                        ),
                    ]
                ]
            ),
            has_spoiler=artwork["r18"],
        )
    except Exception as e:
        logger.error(f"setu_command error: {e.__class__.__name__}:{e}")
        await message.reply(
            i18n.t("bot.msg.manyacg.setu_error", locale=lang),
        )
        return


@PyrogramClient.on_message(pyrogram.filters.command("randavatar"), group=0)
async def randavatar_command(client: PyrogramClient, message: pyrogram.types.Message):
    if not manyacg_client or not aniobjcut.aniobjcut_client:
        return
    chat = message.chat
    user = message.sender_chat or message.from_user
    if not user or not user.id:
        return
    if not chat or not chat.type or not chat.id:
        return
    if chat.type in (pyrogram.enums.ChatType.SUPERGROUP, pyrogram.enums.ChatType.GROUP):
        chat_config = await database.get_chat_config(chat.id)
        if not chat_config.setu_enabled:
            await message.reply(
                i18n.t("bot.msg.manyacg.chat_setu_disabled", locale=chat_config.lang)
            )
            return
        lang = chat_config.lang
    else:
        user_config = await database.get_user_config(user.id)
        lang = user_config.lang
    if await common.memttlcache.get(
        f"setu_cd:{user.id}",
        default=False,
    ):
        await message.reply(
            i18n.t("bot.msg.manyacg.setu_cd", locale=lang),
        )
        return
    await common.memttlcache.set(
        f"setu_cd:{user.id}",
        True,
        ttl=app_config.manyacg_randavatar_cd,
    )
    try:
        resp = await manyacg_client.random_artwork(limit=1, r18=2)
        if resp.status_code != 200:
            await message.reply(
                i18n.t("bot.msg.manyacg.setu_error", locale=lang),
            )
            return
        artwork: dict = resp.json()["data"][0]
        picture: dict = artwork["pictures"][
            random.randint(0, len(artwork["pictures"]) - 1)
        ]
        detail_link = (
            f"https://t.me/{app_config.manyacg_channel}/{picture['message_id']}"
            if picture.get("message_id")
            else artwork["source_url"]
        )
        async with httpx.AsyncClient(timeout=30) as http_client:
            fileresp = await http_client.get(
                f"{app_config.manyacg_api_url}/picture/file/{picture['id']}"
            )
            fileresp.raise_for_status()
        avatar = await aniobjcut.aniobjcut_client.cut_avatar(fileresp.content)
        await message.reply_photo(
            photo=io.BytesIO(avatar),
            caption=f"<a href='{artwork['source_url']}'>{html.escape(artwork['title'])}</a>",
            parse_mode=pyrogram.enums.ParseMode.HTML,
            reply_markup=pyrogram.types.InlineKeyboardMarkup(
                [
                    [
                        pyrogram.types.InlineKeyboardButton(
                            text=i18n.t("bot.button.manyacg.detail", locale=lang),
                            url=detail_link,
                        ),
                        pyrogram.types.InlineKeyboardButton(
                            text=i18n.t("bot.button.manyacg.original", locale=lang),
                            url=f"https://t.me/{app_config.manyacg_bot}/?start=file_{picture['id']}",
                        ),
                    ]
                ]
            ),
            has_spoiler=artwork["r18"],
        )
    except Exception as e:
        logger.error(f"error: {e.__class__.__name__}:{e}")
        await message.reply(
            i18n.t("bot.msg.manyacg.setu_error", locale=lang),
        )
        return
