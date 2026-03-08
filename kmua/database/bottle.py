import sqlalchemy
from sqlalchemy.ext.asyncio import AsyncSession

from kmua.config import app_config
from kmua.database.db import with_session, with_tx
from kmua.database.models import Bottle, BottleReply, UserData


@with_tx
async def pick_random_bottle(session: AsyncSession | None = None) -> Bottle | None:
    assert session is not None, "Session must be provided"
    random_bottle_stmt = (
        sqlalchemy.select(Bottle).order_by(sqlalchemy.func.random()).limit(1)
    )
    result = await session.execute(random_bottle_stmt)
    bottle = result.scalar_one_or_none()
    if bottle is None:
        return None
    await increment_bottle_picks(bottle.id, session)
    return bottle


@with_tx
async def add_bottle(
    sender_id: int,
    text: str | None,
    file_id: str | None,
    media_type: str | None,
    cost: int = app_config.cost_throw_bottle_base,
    session: AsyncSession | None = None,
):
    assert session is not None, "Session must be provided"
    user = await session.get(UserData, sender_id)
    if user is None:
        raise ValueError("User not found")
    config = user.user_config
    if config.coins < 0:
        raise ValueError("Not enough coins to throw a bottle")
    if cost > 0:
        config.coins = max(-144 * 16, config.coins - cost)
    user.user_config = config
    bottle = Bottle(
        sender_id=sender_id,
        text=text,
        picks=0,
        reports=0,
        file_id=file_id,
        media_type=media_type,
    )
    session.add(bottle)


@with_tx
async def increment_bottle_picks(bottle_id: int, session: AsyncSession | None = None):
    assert session is not None, "Session must be provided"
    stmt = (
        sqlalchemy.update(Bottle)
        .where(Bottle.id == bottle_id)
        .values(
            picks=Bottle.picks + 1,
            last_picked_at=sqlalchemy.func.now(),
        )
    )
    await session.execute(stmt)


@with_tx
async def report_bottle(bottle_id: int, session: AsyncSession | None = None):
    assert session is not None, "Session must be provided"
    stmt = (
        sqlalchemy.update(Bottle)
        .where(Bottle.id == bottle_id)
        .values(
            reports=Bottle.reports + 1,
        )
    )
    await session.execute(stmt)


@with_tx
async def delete_bottle(bottle_id: int, session: AsyncSession | None = None):
    assert session is not None, "Session must be provided"
    bottle = await session.get(Bottle, bottle_id)
    if bottle:
        await session.delete(bottle)


@with_session
async def count_bottles(session: AsyncSession | None = None) -> int:
    assert session is not None, "Session must be provided"
    stmt = sqlalchemy.select(sqlalchemy.func.count()).select_from(Bottle)
    result = await session.execute(stmt)
    return result.scalar() or 0


@with_session
async def get_bottle_by_id(
    bottle_id: int, session: AsyncSession | None = None
) -> Bottle | None:
    assert session is not None

    bottle = await session.get(Bottle, bottle_id)
    return bottle


@with_tx
async def add_bottle_reply(
    bottle_id: int,
    replier_id: int,
    text: str,
    is_anonymous: bool = False,
    file_id: str | None = None,
    media_type: str | None = None,
    session: AsyncSession | None = None,
) -> BottleReply:
    assert session is not None
    reply = BottleReply(
        bottle_id=bottle_id,
        replier_id=replier_id,
        text=text,
        is_anonymous=is_anonymous,
        file_id=file_id,
        media_type=media_type,
    )
    session.add(reply)
    await session.flush()
    return reply


@with_session
async def get_bottle_reply_by_id(
    reply_id: int, session: AsyncSession | None = None
) -> BottleReply | None:
    assert session is not None
    return await session.get(BottleReply, reply_id)


@with_tx
async def get_bottle_replies(
    bottle_id: int, session: AsyncSession | None = None
) -> list[BottleReply]:
    assert session is not None
    stmt = (
        sqlalchemy.select(BottleReply)
        .where(BottleReply.bottle_id == bottle_id)
        .order_by(BottleReply.created_at.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


@with_tx
async def delete_bottles_by_sender(
    sender_id: int, session: AsyncSession | None = None
) -> int:
    assert session is not None
    count_stmt = (
        sqlalchemy.select(sqlalchemy.func.count())
        .select_from(Bottle)
        .where(Bottle.sender_id == sender_id)
    )
    count_result = await session.execute(count_stmt)
    count = count_result.scalar() or 0
    if count > 0:
        delete_stmt = sqlalchemy.delete(Bottle).where(Bottle.sender_id == sender_id)
        await session.execute(delete_stmt)
    return count
