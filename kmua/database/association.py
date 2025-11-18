import random
from typing import AsyncGenerator, Sequence

import sqlalchemy
import sqlalchemy.dialects
import sqlalchemy.dialects.mysql
import sqlalchemy.dialects.postgresql
import sqlalchemy.dialects.sqlite
from sqlalchemy.ext.asyncio import AsyncSession

from kmua import common, enums
from kmua.config import app_config, runtime_config

from .db import AsyncSessionFactory, with_session, with_tx
from .models import ChatData, UserChatAssociation, UserConfig, UserData


@with_session
async def count_associations(session: AsyncSession | None = None):
    assert session is not None
    stmt = sqlalchemy.select(sqlalchemy.func.count()).select_from(UserChatAssociation)
    result = await session.execute(stmt)
    return result.scalar() or 0


@with_tx
async def add_association_in_chat(
    chat: ChatData,
    user: UserData,
    waifu: UserData | None = None,
    session: AsyncSession | None = None,
) -> UserChatAssociation | None:
    assert session is not None
    if runtime_config.db_is_postgres:
        stmt = (
            sqlalchemy.dialects.postgresql.insert(UserChatAssociation)
            .values(
                user_id=user.id,
                chat_id=chat.id,
                waifu_id=waifu.id if waifu else None,
            )
            .on_conflict_do_nothing(index_elements=["user_id", "chat_id"])
            .returning(UserChatAssociation)
        )
    elif runtime_config.db_is_mysql:
        stmt = (
            sqlalchemy.dialects.mysql.insert(UserChatAssociation)
            .values(
                user_id=user.id,
                chat_id=chat.id,
                waifu_id=waifu.id if waifu else None,
            )
            .prefix_with("IGNORE")
            .returning(UserChatAssociation)
        )
    elif runtime_config.db_is_sqlite:
        stmt = (
            sqlalchemy.dialects.sqlite.insert(UserChatAssociation)
            .values(
                user_id=user.id,
                chat_id=chat.id,
                waifu_id=waifu.id if waifu else None,
            )
            .on_conflict_do_nothing(index_elements=["user_id", "chat_id"])
            .returning(UserChatAssociation)
        )
    else:
        if data := await session.get(UserChatAssociation, (user.id, chat.id)):
            return data
        member = UserChatAssociation(
            user_id=user.id,
            chat_id=chat.id,
            waifu_id=waifu.id if waifu else None,
        )
        session.add(member)
        return member

    result = await session.execute(stmt)
    association = result.scalars().first()
    if association is not None:
        return association
    return await session.get(UserChatAssociation, (user.id, chat.id))


@with_session
async def get_association(
    user_id: int, chat_id: int, session: AsyncSession | None = None
) -> UserChatAssociation | None:
    assert session is not None
    return await session.get(UserChatAssociation, (user_id, chat_id))


@with_tx
async def update_association(
    association: UserChatAssociation,
    session: AsyncSession | None = None,
):
    assert session is not None

    stmt = (
        sqlalchemy.update(UserChatAssociation)
        .where(
            UserChatAssociation.user_id == association.user_id,
            UserChatAssociation.chat_id == association.chat_id,
        )
        .values(
            waifu_id=association.waifu_id,
            is_bot_admin=association.is_bot_admin,
            promoted_by=association.promoted_by,
        )
    )
    await session.execute(stmt)


@with_tx
async def remove_association(
    user_id: int, chat_id: int, session: AsyncSession | None = None
) -> bool:
    assert session is not None
    stmt = (
        sqlalchemy.delete(UserChatAssociation)
        .where(
            UserChatAssociation.user_id == user_id,
            UserChatAssociation.chat_id == chat_id,
        )
        .returning(UserChatAssociation.user_id)
    )
    result = await session.execute(stmt)
    deleted = result.scalars().first()
    return deleted is not None


@with_session
async def get_user_waifu_in_chat(
    user: UserData, chat: ChatData, session: AsyncSession | None = None
) -> tuple[UserData | None, bool]:
    """get user waifu in chat
    if user is married, return married waifu

    Returns:
        - UserData | None: waifu
        - bool: return is married waifu
    """
    assert session is not None

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
async def get_setted_waifu_in_chat(
    user: UserData, chat: ChatData, session: AsyncSession | None = None
) -> UserData | None:
    """get user setted waifu in chat"""
    assert session is not None

    association = await get_association(user.id, chat.id, session)
    if association is None or association.waifu_id is None:
        return None
    waifu = await session.get(UserData, association.waifu_id)
    return waifu


@with_session
async def is_setted_waifu_in_chat(
    user: UserData, chat: ChatData, session: AsyncSession | None = None
) -> bool:
    """check if user waifu is set in chat"""
    association = await get_association(user.id, chat.id, session)
    if association is None:
        return False
    return association.waifu_id is not None


@with_tx
async def set_user_waifu_in_chat(
    user: UserData, chat: ChatData, waifu: UserData, session: AsyncSession | None = None
) -> bool:
    association = await get_association(user.id, chat.id, session)
    if association is None:
        raise ValueError("Association not found")
    if association.waifu_id is not None:
        raise ValueError("Waifu already set")
    association.waifu_id = waifu.id
    return True


@with_tx
async def unset_user_waifu_in_chat(
    user: UserData, chat: ChatData, session: AsyncSession | None = None
) -> bool:
    association = await get_association(user.id, chat.id, session)
    if association is None:
        raise ValueError("Association not found")
    if association.waifu_id is None:
        raise ValueError("Waifu not set")
    association.waifu_id = None
    return True


@with_tx
async def unset_chat_waifus_by_waifu(
    chat: ChatData, waifu_id: int, session: AsyncSession | None = None
):
    assert session is not None

    stmt = (
        sqlalchemy.update(UserChatAssociation)
        .where(
            UserChatAssociation.chat_id == chat.id,
            UserChatAssociation.waifu_id == waifu_id,
        )
        .values(waifu_id=None)
    )
    await session.execute(stmt)


@with_session
async def take_waifu_for_user_in_chat(
    user: UserData, chat: ChatData, session: AsyncSession | None = None
) -> UserData | None:
    assert session is not None

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

    return waifu


def get_chat_user_participated_waifu(
    chat_id: int, batch_size: int = 100
) -> AsyncGenerator[UserData, None]:
    async def user_generator():
        async with AsyncSessionFactory() as session:
            offset = 0

            while True:
                users_with_waifu_stmt = (
                    sqlalchemy.select(UserData.id)
                    .join(
                        UserChatAssociation,
                        (UserChatAssociation.user_id == UserData.id)
                        & (UserChatAssociation.chat_id == chat_id),
                    )
                    .where(UserChatAssociation.waifu_id.isnot(None))
                )

                users_as_waifu_stmt = sqlalchemy.select(
                    UserChatAssociation.waifu_id
                ).where(
                    (UserChatAssociation.chat_id == chat_id)
                    & (UserChatAssociation.waifu_id.isnot(None))
                )

                union_stmt = sqlalchemy.union(
                    users_with_waifu_stmt, users_as_waifu_stmt
                ).subquery()

                stmt = (
                    sqlalchemy.select(UserData)
                    .where(UserData.id.in_(sqlalchemy.select(union_stmt.c.id)))
                    .offset(offset)
                    .limit(batch_size)
                )

                result = await session.execute(stmt)
                batch = result.scalars().all()

                if not batch:
                    break

                for user in batch:
                    yield user

                offset += batch_size

    return user_generator()


@with_session
async def count_chat_waifu_participants(
    chat_id: int, session: AsyncSession | None = None
) -> int:
    assert session is not None

    users_with_waifu_stmt = (
        sqlalchemy.select(UserData.id)
        .join(
            UserChatAssociation,
            (UserChatAssociation.user_id == UserData.id)
            & (UserChatAssociation.chat_id == chat_id),
        )
        .where(UserChatAssociation.waifu_id.isnot(None))
    )

    users_as_waifu_stmt = sqlalchemy.select(UserChatAssociation.waifu_id).where(
        (UserChatAssociation.chat_id == chat_id)
        & (UserChatAssociation.waifu_id.isnot(None))
    )

    stmt = sqlalchemy.union(users_with_waifu_stmt, users_as_waifu_stmt).subquery()

    count_stmt = sqlalchemy.select(sqlalchemy.func.count()).select_from(stmt)
    count_result = await session.execute(count_stmt)
    return count_result.scalar() or 0


@with_tx
async def cleanup_waifu_data(session: AsyncSession | None = None):
    assert session is not None

    stmt = (
        sqlalchemy.update(UserChatAssociation)
        .where(UserChatAssociation.waifu_id.isnot(None))
        .values(waifu_id=None)
    )
    await session.execute(stmt)


@with_session
async def get_chat_associations(
    chat_id: int, session: AsyncSession | None = None
) -> Sequence[UserChatAssociation]:
    assert session is not None

    stmt = sqlalchemy.select(UserChatAssociation).where(
        UserChatAssociation.chat_id == chat_id
    )
    result = await session.execute(stmt)
    return result.scalars().all()


@with_tx
async def change_user_waifu_in_chat(
    user_id: int,
    chat: ChatData,
    cost: int = app_config.cost_user_change_waifu_base,
    session: AsyncSession | None = None,
) -> UserData | None:
    assert session is not None

    user = await session.get(UserData, user_id)
    if user is None:
        raise ValueError("User not found")
    association = await get_association(user.id, chat.id, session)
    if association is None:
        raise ValueError("Association not found")
    association.waifu_id = None
    config = user.user_config
    if config.coins < 0:
        raise ValueError("Not enough coins")
    config.coins = max(-144 * 16, config.coins - cost)
    user.user_config = config
    new_waifu = await take_waifu_for_user_in_chat(user, chat, session)
    if new_waifu is None:
        return None
    association.waifu_id = new_waifu.id
    return new_waifu
