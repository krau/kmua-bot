import asyncio
import datetime
import shutil
from collections import defaultdict
from io import BytesIO
from pathlib import Path

import aiofiles
import aiofiles.os

from kmua import consts, database, enums
from kmua.bot import client
from kmua.common.memory_store import memstore
from kmua.config import app_config
from kmua.logger import logger


def cleanup_avatar_cache():
    shutil.rmtree(app_config.avatar_cache_dir, ignore_errors=True)


def _get_avatar_path(user_id: int, big: bool = True) -> Path:
    return (
        app_config.avatar_cache_dir / str(user_id)[:2] / f"{user_id}.jpg"
        if big
        else app_config.avatar_cache_dir / str(user_id)[:2] / f"{user_id}_small.jpg"
    )


async def _get_avatar_bytes(
    chat_id: int, big: bool = True, force_refresh: bool = False
) -> tuple[bytes | None, bool]:
    """Get avatar bytes for a chat.
    Returns:
        bytes | None: The avatar bytes if available, None if not.
        bool: True if the avatar was refreshed, False if it was loaded from cache.
    """
    if await memstore.get(enums.GLockKey.CLEANING):
        return None, False
    avatar_path = _get_avatar_path(chat_id, big)
    if await aiofiles.os.path.exists(avatar_path) and not force_refresh:
        async with aiofiles.open(avatar_path, "rb") as avatar_file:
            return (await avatar_file.read(), False)
    chat_full = await client.get_chat(chat_id, True)
    if not chat_full.photo:
        return None, False
    photo_id = chat_full.photo.big_file_id if big else chat_full.photo.small_file_id
    file = await client.download_media(photo_id, in_memory=True)
    if not file or not isinstance(file, BytesIO):
        return None, False
    file.seek(0)
    avatar = file.read()
    await aiofiles.os.makedirs(avatar_path.parent, exist_ok=True)
    async with aiofiles.open(avatar_path, "wb") as avatar_file:
        await avatar_file.write(avatar)
    return avatar, True


class ChatAvatar:
    _locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self._lock = self._locks[chat_id]
        self._path_big = _get_avatar_path(chat_id, True)
        self._path_small = _get_avatar_path(chat_id, False)

    async def save_if_not_exists(self, big: bool = True):
        async with self._lock:
            if big:
                if not await aiofiles.os.path.exists(self._path_big):
                    file, _ = await _get_avatar_bytes(
                        self.chat_id, big=True, force_refresh=True
                    )
                    if file is not None:
                        await database.update_user_avatar(
                            user_id=self.chat_id, refreshed=True
                        )
            else:
                if not await aiofiles.os.path.exists(self._path_small):
                    file, _ = await _get_avatar_bytes(
                        self.chat_id, big=False, force_refresh=True
                    )
                    if file is not None:
                        await database.update_user_avatar(
                            user_id=self.chat_id, refreshed=True
                        )

    async def get_bytes(self, big: bool = True) -> bytes | None:
        async with self._lock:
            user = await database.get_user_by_id(self.chat_id)
            if user is None:
                return None
            force_refresh = False
            if user.update_avatar_at is None or (
                datetime.datetime.now(datetime.timezone.utc) - user.update_avatar_at
            ) > datetime.timedelta(seconds=app_config.avatar_expire):
                force_refresh = True
            if force_refresh:
                logger.debug(f"Refreshing avatar for chat {self.chat_id}")
                avatar, _ = await _get_avatar_bytes(
                    self.chat_id, big=True, force_refresh=True
                )
                await _get_avatar_bytes(self.chat_id, big=False, force_refresh=True)
                await database.update_user_avatar(user_id=self.chat_id, refreshed=True)
            else:
                avatar, _ = await _get_avatar_bytes(self.chat_id, big=big)
            return avatar

    async def get_or_default_bytes(self, big: bool = True) -> bytes:
        avatar = await self.get_bytes(big)
        if avatar is not None:
            return avatar
        default_path = (
            consts.DEFAULT_BIG_AVATAR_PATH if big else consts.DEFAULT_SMALL_AVATAR_PATH
        )
        async with aiofiles.open(default_path, "rb") as default_file:
            return await default_file.read()

    async def get_big_photo(self) -> bytes | str | None:
        """Get the big size photo to send of the chat.

        Returns:
            bytes | str | None: The cached file_id if available, or the bytes of the photo if not cached or cache is outdated.
        """
        async with self._lock:
            user = await database.get_user_by_id(self.chat_id)
            if user is None:
                return None
            outdated = False
            if user.update_avatar_at is None or (
                datetime.datetime.now(datetime.timezone.utc) - user.update_avatar_at
            ) > datetime.timedelta(seconds=app_config.avatar_expire):
                outdated = True
            if outdated:
                logger.debug(f"Refreshing avatar for chat {self.chat_id}")
                avatar, _ = await _get_avatar_bytes(
                    self.chat_id, big=True, force_refresh=True
                )
                await database.update_user_avatar(user_id=self.chat_id, refreshed=True)
                return avatar
            if user.avatar_big_id:
                return user.avatar_big_id
            avatar, refreshed = await _get_avatar_bytes(self.chat_id, big=True)
            if not avatar:
                return None
            if refreshed:
                await database.update_user_avatar(
                    user_id=self.chat_id,
                    refreshed=True,
                )
            return avatar
