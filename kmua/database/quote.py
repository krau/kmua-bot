import random

import sqlalchemy
import sqlalchemy.orm
from sqlalchemy.ext.asyncio import AsyncSession

from kmua.database.db import with_session, with_tx
from kmua.database.models import ChatData, Quote, UserData


@with_session
async def get_quote_by_link(
    link: str, session: AsyncSession | None = None
) -> Quote | None:
    return await session.get(Quote, link)


@with_tx
async def add_quote(
    chat: ChatData,
    user: UserData,
    qer: UserData,
    link: str,
    message_id: int,
    text: str | None = None,
    img: str | None = None,
    session: AsyncSession | None = None,
):
    if await session.get(Quote, link):
        return
    quote = Quote(
        chat_id=chat.id,
        user_id=user.id,
        message_id=message_id,
        link=link,
        qer_id=qer.id,
        text=text,
        img=img,
    )
    session.add(quote)


@with_session
async def get_chat_random_quote(
    chat_id: int, session: AsyncSession | None = None
) -> Quote | None:
    count_stmt = sqlalchemy.select(sqlalchemy.func.count()).where(
        Quote.chat_id == chat_id
    )
    result = await session.execute(count_stmt)
    count = result.scalar_one()

    if count == 0:
        return None

    random_offset = random.randint(0, count - 1)
    quote_stmt = (
        sqlalchemy.select(Quote)
        .options(sqlalchemy.orm.selectinload(Quote.user))
        .where(Quote.chat_id == chat_id)
        .offset(random_offset)
        .limit(1)
    )
    result = await session.execute(quote_stmt)
    return result.scalar_one_or_none()


@with_tx
async def delete_quote(link: str, session: AsyncSession | None = None) -> None:
    quote = await session.get(Quote, link)
    await session.delete(quote)
