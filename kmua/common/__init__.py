import html
import shutil
from io import BytesIO
from pathlib import Path

import aiofiles
import aiofiles.os
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.types import Chat, Photo, User

from kmua import database, enums
from kmua.bot import client
from kmua.config import app_config
from kmua.database.models import ChatData, UserData

from .jobs import jobqueue  # noqa: F401
from .memory_store import memstore  # noqa: F401


async def mention_html(chat: User | Chat | UserData | ChatData) -> str:
    if isinstance(chat, ChatData):
        raise NotImplementedError
    db_user = await database.upsert_user(chat)
    if not db_user.is_real_user and db_user.username is not None:
        return f"<a href='https://t.me/{db_user.username}'>{html.escape(db_user.full_name)}</a>"
    return f"<a href='tg://user?id={chat.id}'>{html.escape(chat.full_name)}</a>"


async def can_user_manage_bot_in_chat(user: User, chat: Chat) -> bool:
    if chat.type == ChatType.PRIVATE:
        raise ValueError("Chat must not be private")
    if user.id == enums.ChatID.ANONYMOUS_ADMIN:
        return True
    db_user = await database.get_user_by_id(user.id)
    if db_user is None:
        raise ValueError("User not found")
    if db_user.is_bot_global_admin:
        return True
    association = await database.get_association(user.id, chat.id)
    if association is None:
        return False
    if association.is_bot_admin:
        return True
    chat_member = await client.get_chat_member(chat.id, user.id)
    if chat_member.status == ChatMemberStatus.OWNER:
        association.is_bot_admin = True
        await database.update_association(user.id, chat.id, association)
        return True
    return False


def _get_avatar_path(user_id: int, big: bool = True) -> Path:
    return (
        app_config.avatar_cache_dir / str(user_id)[:2] / f"{user_id}.jpg"
        if big
        else app_config.avatar_cache_dir / str(user_id)[:2] / f"{user_id}_small.jpg"
    )


async def get_big_avatar_bytes(user_id: int) -> bytes | None:
    if await memstore.get(enums.GLockKey.CLEANING):
        return None
    avatar_path = _get_avatar_path(user_id)
    if await aiofiles.os.path.exists(avatar_path):
        async with aiofiles.open(avatar_path, "rb") as avatar_file:
            return await avatar_file.read()
    photos: list[Photo] = [p async for p in client.get_chat_photos(user_id, limit=1)]
    if not photos:
        return None
    photo = photos[0]
    file = await client.download_media(photo, in_memory=True)
    if file is None or not isinstance(file, BytesIO):
        return None
    file.seek(0)
    avatar = file.read()
    await aiofiles.os.makedirs(avatar_path.parent, exist_ok=True)
    async with aiofiles.open(avatar_path, "wb") as avatar_file:
        await avatar_file.write(avatar)
    return avatar


async def get_small_avatar_bytes(user_id: int) -> bytes | None:
    if await memstore.get(enums.GLockKey.CLEANING):
        return None
    avatar_path = _get_avatar_path(user_id, big=False)
    if await aiofiles.os.path.exists(avatar_path):
        async with aiofiles.open(avatar_path, "rb") as avatar_file:
            return await avatar_file.read()
    photos: list[Photo] = [p async for p in client.get_chat_photos(user_id, limit=1)]
    if not photos:
        return None
    photo: Photo = photos[0]
    file = await client.download_media(photo.thumbs[0], in_memory=True)
    if file is None or not isinstance(file, BytesIO):
        return None
    file.seek(0)
    avatar = file.read()
    await aiofiles.os.makedirs(avatar_path.parent, exist_ok=True)
    async with aiofiles.open(avatar_path, "wb") as avatar_file:
        await avatar_file.write(avatar)
    return avatar


def cleanup_avatar_cache():
    shutil.rmtree(app_config.avatar_cache_dir, ignore_errors=True)
