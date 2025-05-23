import datetime

from pyrogram.enums import ChatType
from pyrogram.types import Chat, User
from sqlalchemy import func, select, text, update

from .db import get_session
from .models import UserConfig, UserData


async def get_user_by_id(id: int) -> UserData | None:
    async with get_session() as session:
        user = await session.get(UserData, id)
        if user is None:
            return None
        session.expunge(user)
        return user


async def upsert_user(user: User | Chat) -> UserData:
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
    if isinstance(user, User):
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
        raise TypeError("user must be User or Chat")
    async with get_session() as session:
        async with session.begin():
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
                session.expunge(user_data)
            return user_data


async def get_user_config(user: int | UserData | User) -> UserConfig:
    if isinstance(user, UserData):
        return UserConfig.from_dict(user.config)
    elif isinstance(user, User):
        user_data = await upsert_user(user)
    elif isinstance(user, int):
        user_data = await get_user_by_id(user)
    else:
        raise TypeError("user must be int, UserData or User")
    if user_data is None:
        raise ValueError("user not found")
    return UserConfig.from_dict(user_data.config)


async def count_users() -> int:
    """
    Count all users in the database.
    """
    async with get_session() as session:
        stmt = select(func.count()).select_from(UserData)
        result = await session.execute(stmt)
        count = result.scalar_one()
        return count


async def get_inactived_users_count(days: int) -> int:
    """
    Count all users in the database who are inactive for more than `days` days.
    """
    async with get_session() as session:
        stmt = (
            select(func.count())
            .select_from(UserData)
            .where(
                UserData.updated_at
                < datetime.datetime.now() - datetime.timedelta(days=days)
            )
        )
        result = await session.execute(stmt)
        count = result.scalar_one()
        return count


async def clean_inactived_users_avatar(days: int) -> int:
    """
    Clean all users in the database who are inactive for more than `days` days.
    """
    threshold = datetime.datetime.now() - datetime.timedelta(days=days)
    stmt = (
        update(UserData)
        .where(UserData.updated_at < threshold)
        .values(
            avatar_big_id=None,
            avatar_small_blob=None,
            avatar_big_blob=None,
        )
        .execution_options(synchronize_session="fetch")  # 保持 ORM 状态一致性
    )
    async with get_session() as session:
        async with session.begin():
            result = await session.execute(stmt)
            await session.commit()
            if session.bind.dialect.name == "sqlite":
                await session.execute(text("VACUUM"))
            else:
                await session.execute(text("OPTIMIZE TABLE user_data"))
            await session.commit()
            return result.rowcount
