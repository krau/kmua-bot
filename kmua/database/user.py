import sqlalchemy
from pyrogram.enums import ChatType
from pyrogram.types import Chat, User
from sqlalchemy.ext.asyncio import AsyncSession

from .db import with_session, with_tx
from .models import UserChatAssociation, UserConfig, UserData


@with_session
async def get_user_by_id(id: int, session: AsyncSession | None = None) -> UserData:
    return await session.get(UserData, id)


@with_tx
async def upsert_user(
    user: User | Chat | UserData, session: AsyncSession | None = None
) -> UserData:
    """
    'Upsert' user data into the database.
    Only fields [id, username, full_name, is_bot, is_real_user] are upsert.
    """
    if user.id is None:
        raise ValueError("user.id must not be None")
    username = None
    full_name = None
    is_real_user = True
    is_bot = False
    if isinstance(user, (User, UserData)):
        username = user.username
        full_name = user.full_name
        is_bot = user.is_bot
        is_real_user = not user.is_bot
    elif isinstance(user, Chat):
        username = user.username
        full_name = user.title
        is_bot = False
        is_real_user = user.type == ChatType.PRIVATE
    else:
        raise TypeError("user must be User, Chat or UserData")
    user_data = await session.get(UserData, user.id)
    if user_data is None:
        user_data = UserData(
            id=user.id,
            username=username,
            full_name=full_name,
            is_bot=is_bot,
            is_real_user=is_real_user,
        )
        session.add(user_data)
    else:
        user_data.username = username  # type: ignore
        user_data.full_name = full_name  # type: ignore
        user_data.is_bot = is_bot  # type: ignore
        user_data.is_real_user = is_real_user  # type: ignore
    return user_data


async def get_user_config(user: int | UserData | User) -> UserConfig:
    if isinstance(user, UserData):
        return UserConfig.from_dict(user.config)
    user_data: UserData | None = None
    if isinstance(user, User):
        user_data = await upsert_user(user)
    elif isinstance(user, int):
        user_data = await get_user_by_id(user)
    else:
        raise TypeError("user must be int, UserData or User")
    if user_data is None:
        raise ValueError("user not found")
    return user_data.user_config


@with_tx
async def update_user_config(
    user_id: int, config: UserConfig, session: AsyncSession | None = None
) -> UserConfig:
    user_data = await session.get(UserData, user_id)
    if user_data is None:
        raise ValueError(f"User with id {user_id} not found")
    user_data.user_config = config
    return user_data.user_config


@with_tx
async def update_user_avatar(
    user_id: int,
    avatar_big_blob: bytes | None = None,
    avatar_big_id: str | None = None,
    avatar_small_blob: bytes | None = None,
    session: AsyncSession | None = None,
) -> UserData:
    user_data = await session.get(UserData, user_id)
    if user_data is None:
        raise ValueError(f"User with id {user_id} not found")
    if avatar_big_blob is not None:
        user_data.avatar_big_blob = avatar_big_blob
    if avatar_big_id is not None:
        user_data.avatar_big_id = avatar_big_id
    if avatar_small_blob is not None:
        user_data.avatar_small_blob = avatar_small_blob
    return user_data


@with_tx
async def make_wedding(
    user_id: int,
    waifu_id: int,
    chat_id: int,
    session: AsyncSession | None = None,
):
    user_data = await session.get(UserData, user_id)
    waifu_data = await session.get(UserData, waifu_id)
    if user_data is None or waifu_data is None:
        raise ValueError("User or waifu not found")
    if (
        user_data.married_waifu_id is not None
        or waifu_data.married_waifu_id is not None
    ):
        raise ValueError("User is already married")
    user_data.married_waifu_id = waifu_id
    user_data.is_married = True
    waifu_data.married_waifu_id = user_id
    waifu_data.is_married = True

    stmt = (
        sqlalchemy.update(UserChatAssociation)
        .where(
            sqlalchemy.or_(
                UserChatAssociation.user_id == user_id,
                UserChatAssociation.waifu_id == waifu_id,
                UserChatAssociation.user_id == waifu_id,
                UserChatAssociation.waifu_id == user_id,
            )
        )
        .values(waifu_id=None)
    )
    await session.execute(stmt)
    stmt = (
        sqlalchemy.update(UserChatAssociation)
        .where(
            UserChatAssociation.user_id == user_id,
            UserChatAssociation.chat_id == chat_id,
        )
        .values(waifu_id=waifu_id)
    )
    await session.execute(stmt)
    stmt = (
        sqlalchemy.update(UserChatAssociation)
        .where(
            UserChatAssociation.user_id == waifu_id,
            UserChatAssociation.chat_id == chat_id,
        )
        .values(waifu_id=user_id)
    )
    await session.execute(stmt)


@with_tx
async def cleanup_user_avatars(
    session: AsyncSession | None = None,
) -> None:
    stmt = sqlalchemy.update(UserData).values(
        avatar_big_blob=None,
        avatar_big_id=None,
        avatar_small_blob=None,
    )
    await session.execute(stmt)
    # TODO: refactor to use other service for avatar storage
    if session.bind.dialect.name == "sqlite":
        await session.execute(sqlalchemy.text("VACUUM"))
    elif session.bind.dialect.name == "postgresql":
        await session.execute(sqlalchemy.text("VACUUM FULL"))
    elif session.bind.dialect.name == "mysql":
        await session.execute(sqlalchemy.text("OPTIMIZE TABLE user_data"))
    await session.flush()
