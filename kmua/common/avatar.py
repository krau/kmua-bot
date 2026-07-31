import asyncio
import datetime
import shutil
import weakref
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


# A burst of avatar cache misses (quotes, waifu cards) must not flood the
# Telegram session: refreshes are serialized through a small semaphore, each
# one is hard-timed, and a failure is remembered so hot paths back off for a
# while instead of retrying a dead session on every call.
_avatar_refresh_semaphore = asyncio.Semaphore(
    max(1, app_config.avatar_refresh_concurrency)
)
_avatar_refresh_failed_at: dict[int, float] = {}


async def _get_avatar_bytes(
    chat_id: int,
    big: bool = True,
    force_refresh: bool = False,
    ignore_backoff: bool = False,
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
    loop = asyncio.get_running_loop()
    if (
        not ignore_backoff
        and loop.time() - _avatar_refresh_failed_at.get(chat_id, 0.0)
        < app_config.avatar_refresh_retry_after
    ):
        # A recent refresh attempt failed; don't hammer the session again.
        return None, False
    try:
        async with _avatar_refresh_semaphore:
            async with asyncio.timeout(app_config.avatar_refresh_timeout):
                chat_full = await client.get_chat(chat_id, True)
                if not chat_full.photo:
                    return None, False
                photo_id = (
                    chat_full.photo.big_file_id
                    if big
                    else chat_full.photo.small_file_id
                )
                file = await client.download_media(photo_id, in_memory=True)
                if not file or not isinstance(file, BytesIO):
                    return None, False
                file.seek(0)
                avatar = file.read()
                await aiofiles.os.makedirs(avatar_path.parent, exist_ok=True)
                async with aiofiles.open(avatar_path, "wb") as avatar_file:
                    await avatar_file.write(avatar)
                _avatar_refresh_failed_at.pop(chat_id, None)
                return avatar, True
    except Exception:
        _avatar_refresh_failed_at[chat_id] = loop.time()
        raise


class ChatAvatar:
    _locks = weakref.WeakValueDictionary[int, asyncio.Lock]()

    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        lock = self._locks.get(chat_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[chat_id] = lock
        self._lock = lock
        self._path_big = _get_avatar_path(chat_id, True)
        self._path_small = _get_avatar_path(chat_id, False)

    async def save_if_not_exists(self, big: bool = True) -> bool:
        try:
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
            return True
        except Exception as e:
            logger.error(f"Error saving avatar for chat {self.chat_id}: {e}")
            return False

    async def get_bytes(self, big: bool = True) -> bytes | None:
        try:
            async with self._lock:
                user = await database.get_user_by_id(self.chat_id)
                if user is None:
                    return None
                force_refresh = False
                if user.update_avatar_at is None or (
                    datetime.datetime.now() - user.update_avatar_at
                ) > datetime.timedelta(seconds=app_config.avatar_expire):
                    force_refresh = True
                if force_refresh:
                    logger.debug(f"Refreshing avatar for chat {self.chat_id}")
                    # Refresh only the requested size; the other size is
                    # refreshed lazily on its own first use. Downloading both
                    # here doubles the network load for callers that only need
                    # one (quote/waifu hot paths).
                    avatar, _ = await _get_avatar_bytes(
                        self.chat_id, big=big, force_refresh=True
                    )
                    await database.update_user_avatar(
                        user_id=self.chat_id, refreshed=True
                    )
                    return avatar
                else:
                    avatar, _ = await _get_avatar_bytes(self.chat_id, big=big)
                    return avatar
        except Exception as e:
            logger.error(f"Error getting avatar for chat {self.chat_id}: {e}")
            return None

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
        try:
            async with self._lock:
                user = await database.get_user_by_id(self.chat_id)
                if user is None:
                    return None
                outdated = False
                if user.update_avatar_at is None or (
                    datetime.datetime.now() - user.update_avatar_at
                ) > datetime.timedelta(seconds=app_config.avatar_expire):
                    outdated = True
                if outdated:
                    logger.debug(f"Refreshing avatar for chat {self.chat_id}")
                    avatar, _ = await _get_avatar_bytes(
                        self.chat_id, big=True, force_refresh=True
                    )
                    await database.update_user_avatar(
                        user_id=self.chat_id, refreshed=True
                    )
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
        except Exception as e:
            logger.error(f"Error getting big avatar for chat {self.chat_id}: {e}")
            return None

    async def force_refresh(self) -> bool:
        try:
            async with self._lock:
                # Explicit user action: always try, even if a recent refresh
                # attempt failed (backoff is for the hot paths only).
                avatar_b, refreshed_big = await _get_avatar_bytes(
                    self.chat_id, big=True, force_refresh=True, ignore_backoff=True
                )
                avatar_s, refreshed_small = await _get_avatar_bytes(
                    self.chat_id, big=False, force_refresh=True, ignore_backoff=True
                )
                if all((avatar_b, avatar_s, refreshed_big, refreshed_small)):
                    await database.update_user_avatar(
                        user_id=self.chat_id,
                        refreshed=True,
                    )
                    return True
            return False
        except Exception as e:
            logger.error(
                f"Error forcing refresh of avatar for chat {self.chat_id}: {e}"
            )
            return False
