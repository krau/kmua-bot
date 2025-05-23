from pyrogram.enums import ChatType
from pyrogram.types import Chat, User
from sqlalchemy.ext.asyncio import AsyncSession

from .db import with_session, with_tx
from .models import UserConfig, UserData


@with_session
async def get_user_by_id(id: int, session: AsyncSession) -> UserData | None:
    user = await session.get(UserData, id)
    if user is None:
        return None
    return user


@with_tx
async def upsert_user(user: User | Chat, session: AsyncSession) -> UserData:
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
    user_id: int, config: UserConfig, session: AsyncSession
) -> UserConfig:
    user_data = await session.get(UserData, user_id)
    if user_data is None:
        raise ValueError(f"User with id {user_id} not found")
    user_data.user_config = config
    return user_data.user_config


@with_tx
async def update_user(user: UserData, session: AsyncSession) -> UserData:
    user_data = await session.get(UserData, user.id)
    if user_data is None:
        raise ValueError(f"User with id {user.id} not found")
    user_data = user
    return user_data
