import html
import io
import random

import aiofiles
import httpx
import pyrogram
from pyrogram.client import Client as PyrogramClient

from kmua import common, database, i18n
from kmua.config import app_config
from kmua.logger import logger
from kmua.services import aniobjcut
from kmua.services import manyacg as manyacg_service
from kmua.services.manyacg import (
    FetchedPicture,
    FetchedUgoira,
    FetchedVideo,
    manyacg_client,
)

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
    if resp.status != 200:
        logger.error(f"fetch_artwork failed: {resp.status} {resp.message}")
        return
    artwork = resp.data
    assert artwork is not None, "Artwork data is None but status is 200"
    try:
        medias: list[FetchedVideo | FetchedPicture] = []
        if artwork.pictures:
            pictures = [picture for picture in artwork.pictures]
            pictures.sort(key=lambda x: x.index)
            medias += [picture for picture in pictures]
        # [TODO] impl ugoira support
        # if artwork.ugoira_metas and len(medias) < 10:
        #     ugorias = [ugoira for ugoira in artwork.ugoira_metas]
        #     ugorias.sort(key=lambda x: x.index)
        #     medias += [ugoira for ugoira in ugorias]
        if artwork.videos and len(medias) < 10:
            videos = [video for video in artwork.videos]
            videos.sort(key=lambda x: x.index)
            medias += [video for video in videos]
        assert len(medias) > 0, "No media found in artwork"
        caption = f"<a href='{artwork.source_url}'>{html.escape(artwork.title)}</a>\n<blockquote expandable=true>{html.escape(artwork.description)}</blockquote>"
        if (count := len(medias)) > 10:
            caption += i18n.t(
                "bot.msg.manyacg.artwork_pictures_count",
                locale=lang,
            ).format(count=count)
            if artwork.cache_id:
                caption += f" <a href='https://t.me/{app_config.manyacg_bot}/?start=info_{artwork.cache_id}'>{i18n.t('bot.msg.manyacg.seefull', locale=lang)}</a>"
        async with aiofiles.tempfile.TemporaryDirectory() as tmpdir:
            async with httpx.AsyncClient(timeout=60) as http_client:
                inputs = []
                for idx, media in enumerate(medias[:10]):
                    im = await utils.prepare_media(
                        http_client, media, tmpdir + f"/media_{idx}"
                    )
                    if isinstance(media, (FetchedVideo, FetchedUgoira)):
                        input_media = pyrogram.types.InputMediaVideo(
                            media=im,
                            caption=caption if idx == 0 else "",
                            parse_mode=pyrogram.enums.ParseMode.HTML,
                            supports_streaming=True,
                            has_spoiler=artwork.r18,
                        )
                    else:
                        input_media = pyrogram.types.InputMediaPhoto(
                            media=im,
                            caption=caption if idx == 0 else "",
                            parse_mode=pyrogram.enums.ParseMode.HTML,
                            has_spoiler=artwork.r18,
                        )
                    inputs.append(input_media)
                msgs = await message.reply_media_group(
                    inputs,
                )
        for idx, msg in enumerate(msgs):
            media_url = ""
            file_id = ""
            m = medias[idx]
            if isinstance(m, FetchedPicture):
                media_url = m.original
                file_id = msg.photo.file_id if msg.photo else ""
            elif isinstance(m, FetchedUgoira):
                media_url = m.data.original_zip
                file_id = msg.video.file_id if msg.video else ""
            elif isinstance(m, FetchedVideo):
                media_url = m.url
                file_id = msg.video.file_id if msg.video else ""
            if not media_url or not file_id:
                continue
            await common.memttlcache.set(
                f"artwork:media_file_id:{media_url}",
                file_id,
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
        if resp.status != 200:
            await message.reply(
                i18n.t("bot.msg.manyacg.setu_error", locale=lang),
            )
            return
        assert resp.data is not None, "Random artwork data is None but status is 200"
        artwork = resp.data[0]
        picture = artwork.pictures[random.randint(0, len(artwork.pictures) - 1)]
        detail_link = artwork.source_url
        await message.reply_photo(
            photo=picture.regular,
            caption=f"<a href='{artwork.source_url}'>{html.escape(artwork.title)}</a>",
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
                            url=f"https://t.me/{app_config.manyacg_bot}/?start=file_{picture.id}",
                        ),
                    ]
                ]
            ),
            has_spoiler=artwork.r18,
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
        if resp.status != 200:
            await message.reply(
                i18n.t("bot.msg.manyacg.setu_error", locale=lang),
            )
            return
        assert resp.data is not None, "Random artwork data is None but status is 200"
        artwork = resp.data[0]
        picture = artwork.pictures[random.randint(0, len(artwork.pictures) - 1)]
        detail_link = artwork.source_url
        async with httpx.AsyncClient(timeout=30) as http_client:
            fileresp = await http_client.get(
                f"{app_config.manyacg_api_url}/picture/file/{picture.id}",
            )
            fileresp.raise_for_status()
        avatar = await aniobjcut.aniobjcut_client.cut_avatar(fileresp.content)
        await message.reply_photo(
            photo=io.BytesIO(avatar),
            caption=f"<a href='{artwork.source_url}'>{html.escape(artwork.title)}</a>",
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
                            url=f"https://t.me/{app_config.manyacg_bot}/?start=file_{picture.id}",
                        ),
                    ]
                ]
            ),
            has_spoiler=artwork.r18,
        )
    except Exception as e:
        logger.error(f"error: {e.__class__.__name__}:{e}")
        await message.reply(
            i18n.t("bot.msg.manyacg.setu_error", locale=lang),
        )
        return
