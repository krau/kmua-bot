import datetime

import sqlalchemy
import sqlalchemy.dialects
import sqlalchemy.dialects.mysql
import sqlalchemy.dialects.postgresql
import sqlalchemy.dialects.sqlite
from pyrogram.enums import ChatType
from pyrogram.types import Chat, User
from sqlalchemy.ext.asyncio import AsyncSession

from kmua.config import runtime_config

from .db import with_session, with_tx
from .models import UserChatAssociation, UserConfig, UserData


@with_session
async def count_users(session: AsyncSession | None = None) -> int:
    assert session is not None

    stmt = sqlalchemy.select(sqlalchemy.func.count()).select_from(UserData)
    result = await session.execute(stmt)
    return result.scalar() or 0


@with_session
async def get_user_by_id(
    id: int, session: AsyncSession | None = None
) -> UserData | None:
    assert session is not None
    if id is None:
        raise ValueError("id must not be None")
    return await session.get(UserData, id)


@with_tx
async def upsert_user(
    user: User | Chat | UserData, session: AsyncSession | None = None
) -> UserData:
    """
    'Upsert' user data into the database.
    Only fields [id, username, full_name, is_bot, is_real_user] are upsert.
    """
    assert session is not None

    if user.id is None:
        raise ValueError("user.id must not be None")

    username = None
    full_name = str(user.id)
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
        is_real_user = not (user.type is not None and user.type != ChatType.PRIVATE)
    else:
        raise TypeError("user must be User, Chat or UserData")

    if full_name is None:
        raise ValueError("user.full_name must not be None")

    if runtime_config.db_is_postgres:
        stmt = (
            sqlalchemy.dialects.postgresql.insert(UserData)
            .values(
                id=user.id,
                username=username,
                full_name=full_name,
                is_bot=is_bot,
                is_real_user=is_real_user,
            )
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "username": username,
                    "full_name": full_name,
                    "is_bot": is_bot,
                    "is_real_user": is_real_user,
                },
            )
            .returning(UserData)
        )
    elif runtime_config.db_is_mysql:
        stmt = (
            sqlalchemy.dialects.mysql.insert(UserData)
            .values(
                id=user.id,
                username=username,
                full_name=full_name,
                is_bot=is_bot,
                is_real_user=is_real_user,
            )
            .on_duplicate_key_update(
                username=username,
                full_name=full_name,
                is_bot=is_bot,
                is_real_user=is_real_user,
            )
            .returning(UserData)
        )
    elif runtime_config.db_is_sqlite:
        stmt = (
            sqlalchemy.dialects.sqlite.insert(UserData)
            .values(
                id=user.id,
                username=username,
                full_name=full_name,
                is_bot=is_bot,
                is_real_user=is_real_user,
            )
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "username": username,
                    "full_name": full_name,
                    "is_bot": is_bot,
                    "is_real_user": is_real_user,
                },
            )
            .returning(UserData)
        )
    else:
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
            user_data.username = username
            user_data.full_name = full_name
            user_data.is_bot = is_bot or False
            user_data.is_real_user = is_real_user
        return user_data

    result = await session.execute(stmt)
    user_data = result.scalars().first()
    if user_data is not None:
        return user_data
    data = await session.get(UserData, user.id)
    assert data is not None
    return data


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
async def add_user_coins(
    user_id: int, coins: int, session: AsyncSession | None = None
) -> UserConfig:
    assert session is not None

    user_data = await session.get(UserData, user_id)
    if user_data is None:
        raise ValueError(f"User with id {user_id} not found")
    config = user_data.user_config
    config.coins += coins
    user_data.user_config = config
    return user_data.user_config


@with_tx
async def cost_user_coins(
    user_id: int, coins: int, session: AsyncSession | None = None
) -> UserConfig:
    assert session is not None

    user_data = await session.get(UserData, user_id)
    if user_data is None:
        raise ValueError(f"User with id {user_id} not found")
    config = user_data.user_config
    config.coins = max(-144 * 16, config.coins - coins)
    user_data.user_config = config
    return user_data.user_config


@with_tx
async def update_user_config(
    user_id: int, config: UserConfig, session: AsyncSession | None = None
) -> UserConfig:
    assert session is not None

    user_data = await session.get(UserData, user_id)
    if user_data is None:
        raise ValueError(f"User with id {user_id} not found")
    user_data.user_config = config
    return user_data.user_config


@with_tx
async def update_user_avatar(
    user_id: int,
    avatar_big_id: str | None = None,
    refreshed: bool = False,
    session: AsyncSession | None = None,
) -> UserData:
    assert session is not None

    user_data = await session.get(UserData, user_id)
    if user_data is None:
        raise ValueError(f"User with id {user_id} not found")
    user_data.avatar_big_id = avatar_big_id
    if refreshed:
        user_data.update_avatar_at = datetime.datetime.now()
    return user_data


@with_tx
async def update_user(
    user_id: int,
    waifu_mention: bool = False,
    is_bot_global_admin: bool = False,
    session: AsyncSession | None = None,
):
    assert session is not None

    user_data = await session.get(UserData, user_id)
    if user_data is None:
        raise ValueError(f"User with id {user_id} not found")
    user_data.waifu_mention = waifu_mention
    user_data.is_bot_global_admin = is_bot_global_admin


@with_tx
async def make_wedding(
    user_id: int,
    waifu_id: int,
    chat_id: int,
    session: AsyncSession | None = None,
):
    assert session is not None

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
async def cleanup_user_avatar(session: AsyncSession | None = None):
    assert session is not None

    stmt = sqlalchemy.update(UserData).values(avatar_big_id=None)
    await session.execute(stmt)


@with_tx
async def divorce(user_id: int, session: AsyncSession | None = None):
    assert session is not None

    user_data = await session.get(UserData, user_id)
    if user_data is None:
        raise ValueError(f"User with id {user_id} not found")
    if not user_data.is_married or user_data.married_waifu_id is None:
        raise ValueError("User is not married")
    waifu_id = user_data.married_waifu_id
    waifu_data = await session.get(UserData, waifu_id)
    if waifu_data is None:
        raise ValueError(f"Waifu with id {waifu_id} not found")
    if not waifu_data.is_married or waifu_data.married_waifu_id != user_id:
        raise ValueError("Waifu is not married to this user")

    user_data.is_married = False
    user_data.married_waifu_id = None
    waifu_data.is_married = False
    waifu_data.married_waifu_id = None

    stmt = (
        sqlalchemy.update(UserChatAssociation)
        .where(
            sqlalchemy.or_(
                UserChatAssociation.user_id == user_id,
                UserChatAssociation.waifu_id == user_id,
                UserChatAssociation.user_id == waifu_id,
                UserChatAssociation.waifu_id == waifu_id,
            )
        )
        .values(waifu_id=None)
    )
    await session.execute(stmt)
