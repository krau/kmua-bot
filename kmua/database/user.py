from pyrogram.enums import ChatType
from pyrogram.types import Chat, User

from .db import get_session
from .models import UserData


async def get_user_by_id(id: int) -> UserData | None:
    async with get_session() as session:
        user = await session.get(UserData, id)
        if user is None:
            return None
        session.expunge(user)
        return user


async def upsert_user(user: User | Chat) -> UserData:
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
