import html
from io import BytesIO

import pyrogram
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.types import Chat, User

from kmua import database, enums
from kmua.bot import client
from kmua.database.models import ChatData, UserData
from .memstore import memstore  # noqa: F401


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


async def get_big_avatar_bytes(user_id: int) -> bytes | None:
    db_user: UserData = await database.get_user_by_id(user_id)
    if db_user is None:
        return None
    if db_user.avatar_big_blob is not None:
        return db_user.avatar_big_blob
    photos = []
    async for photo in client.get_chat_photos(user_id, limit=1):
        photos.append(photo)
    if photos is None:
        return None
    photo = photos[0]
    file = await client.download_media(photo, in_memory=True)
    if file is None:
        return None
    if not isinstance(file, BytesIO):
        raise ValueError("File is not a BytesIO")
    file.seek(0)
    avatar = file.read()
    db_user.avatar_big_blob = avatar
    await database.update_user_avatar(db_user.id, avatar_big_blob=avatar)
    return avatar


async def get_small_avatar_bytes(user_id: int) -> bytes | None:
    db_user: UserData = await database.get_user_by_id(user_id)
    if db_user is None:
        return None
    if db_user.avatar_small_blob is not None:
        return db_user.avatar_small_blob
    photos = []
    async for photo in client.get_chat_photos(user_id, limit=1):
        photos.append(photo)
    if photos is None:
        return None
    photo: pyrogram.types.Photo = photos[0]
    file = await client.download_media(photo.thumbs[0], in_memory=True)
    if file is None:
        return None
    if not isinstance(file, BytesIO):
        raise ValueError("File is not a BytesIO")
    file.seek(0)
    avatar = file.read()
    db_user.avatar_small_blob = avatar
    await database.update_user_avatar(db_user.id, avatar_small_blob=avatar)
    return avatar
