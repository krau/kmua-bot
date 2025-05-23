from .db import with_session, with_tx
from .models import ChatData, UserChatAssociation, UserData
import sqlalchemy
from sqlalchemy.ext.asyncio import AsyncSession


@with_tx
async def add_association_in_chat(
    chat: ChatData, user: UserData, waifu: UserData | None, session: AsyncSession
) -> UserChatAssociation:
    if data := await session.get(UserChatAssociation, (user.id, chat.id)):
        return data
    member = UserChatAssociation(
        user_id=user.id,
        chat_id=chat.id,
        waifu_id=waifu.id if waifu else None,
    )
    session.add(member)
    return member


@with_session
async def get_association(
    user_id: int, chat_id: int, session: AsyncSession
) -> UserChatAssociation | None:
    data = await session.get(UserChatAssociation, (user_id, chat_id))
    if data is None:
        return None
    return data


@with_tx
async def update_association(
    user_id: int, chat_id: int, association: UserChatAssociation, session: AsyncSession
) -> bool:
    stmt = (
        sqlalchemy.update(UserChatAssociation)
        .where(
            UserChatAssociation.user_id == user_id,
            UserChatAssociation.chat_id == chat_id,
        )
        .values(
            {
                "waifu_id": association.waifu_id,
                "is_bot_admin": association.is_bot_admin,
            }
        )
    )
    result = await session.execute(stmt)
    return result.rowcount > 0


@with_tx
async def remove_association(user_id: int, chat_id: int, session: AsyncSession) -> bool:
    stmt = sqlalchemy.delete(UserChatAssociation).where(
        UserChatAssociation.user_id == user_id,
        UserChatAssociation.chat_id == chat_id,
    )
    result = await session.execute(stmt)
    return result.rowcount > 0
