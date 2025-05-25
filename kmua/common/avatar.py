import asyncio
import shutil
from io import BytesIO
from pathlib import Path

import aiofiles
import aiofiles.os

from kmua import enums
from kmua.bot import client
from kmua.common.memory_store import memstore
from kmua.config import app_config


def cleanup_avatar_cache():
    shutil.rmtree(app_config.avatar_cache_dir, ignore_errors=True)


def _get_avatar_path(user_id: int, big: bool = True) -> Path:
    return (
        app_config.avatar_cache_dir / str(user_id)[:2] / f"{user_id}.jpg"
        if big
        else app_config.avatar_cache_dir / str(user_id)[:2] / f"{user_id}_small.jpg"
    )


async def get_avatar_bytes(
    chat_id: int, big: bool = True, force_refresh: bool = False
) -> bytes | None:
    if await memstore.get(enums.GLockKey.CLEANING):
        return None
    avatar_path = _get_avatar_path(chat_id, big)
    if await aiofiles.os.path.exists(avatar_path) and not force_refresh:
        async with aiofiles.open(avatar_path, "rb") as avatar_file:
            return await avatar_file.read()
    chat_full = await client.get_chat(chat_id, True)
    if not chat_full.photo:
        return None
    photo_id = chat_full.photo.big_file_id if big else chat_full.photo.small_file_id
    file = await client.download_media(photo_id, in_memory=True)
    if not file or not isinstance(file, BytesIO):
        return None
    file.seek(0)
    avatar = file.read()
    await aiofiles.os.makedirs(avatar_path.parent, exist_ok=True)
    async with aiofiles.open(avatar_path, "wb") as avatar_file:
        await avatar_file.write(avatar)
    return avatar


class ChatAvatar:
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self._path_big = _get_avatar_path(chat_id, True)
        self._path_small = _get_avatar_path(chat_id, False)
        self._lock = asyncio.Lock()

    async def save_if_not_exists(self, big: bool = True):
        async with self._lock:
            if big:
                if not await aiofiles.os.path.exists(self._path_big):
                    await get_avatar_bytes(self.chat_id, big=True, force_refresh=True)
            else:
                if not await aiofiles.os.path.exists(self._path_small):
                    await get_avatar_bytes(self.chat_id, big=False, force_refresh=True)
