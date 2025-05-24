from .db import with_session, with_tx
from .models import ChatData, UserChatAssociation, UserData
import sqlalchemy
from sqlalchemy.ext.asyncio import AsyncSession
from kmua import enums


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


@with_session
async def get_user_waifu_in_chat(
    user: UserData, chat: ChatData, session: AsyncSession
) -> tuple[UserData | None, bool]:
    """get user waifu in chat
    if user is married, return married waifu

    Returns:
        - UserData | None: waifu
        - bool: return is married waifu
    """
    if user.married_waifu_id is not None:
        waifu = await session.get(UserData, user.married_waifu_id)
        if waifu is not None:
            return waifu, True
    association = await get_association(user.id, chat.id, session)
    if association is None or association.waifu_id is None:
        return None, False
    waifu = await session.get(UserData, association.waifu_id)
    return waifu, False


@with_session
async def is_setted_waifu_in_chat(
    user: UserData, chat: ChatData, session: AsyncSession
) -> bool:
    """check if user waifu is set in chat"""
    association = await get_association(user.id, chat.id, session)
    if association is None:
        return False
    return association.waifu_id is not None


@with_tx
async def set_user_waifu_in_chat(
    user: UserData, chat: ChatData, waifu: UserData, session: AsyncSession
) -> bool:
    association = await get_association(user.id, chat.id, session)
    if association is None:
        raise ValueError("Association not found")
    if association.waifu_id is not None:
        raise ValueError("Waifu already set")
    association.waifu_id = waifu.id
    return True


@with_tx
async def remove_user_waifu_in_chat(
    user: UserData, chat: ChatData, session: AsyncSession
) -> bool:
    association = await get_association(user.id, chat.id, session)
    if association is None:
        raise ValueError("Association not found")
    if association.waifu_id is None:
        raise ValueError("Waifu not set")
    association.waifu_id = None
    return True


@with_session
async def take_waifu_for_user_in_chat(
    user: UserData, chat: ChatData, session: AsyncSession
) -> UserData | None:
    excluded_user_ids = [
        user.id,
        enums.ChatID.ANONYMOUS_ADMIN,
        enums.ChatID.SERVICE_CHAT,
        enums.ChatID.FAKE_CHANNEL,
    ]

    stmt = (
        sqlalchemy.select(UserData)
        .join(
            UserChatAssociation,
            (UserChatAssociation.user_id == UserData.id)
            & (UserChatAssociation.chat_id == chat.id),
        )
        .where(
            sqlalchemy.and_(
                sqlalchemy.not_(UserData.is_bot),
                sqlalchemy.not_(UserData.is_married),
                sqlalchemy.not_(UserData.id.in_(excluded_user_ids)),
            )
        )
        .order_by(sqlalchemy.func.random())
        .limit(1)
    )

    result = await session.execute(stmt)
    waifu = result.scalars().first()

    if waifu is None:
        return None

    return waifu
