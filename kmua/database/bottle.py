import random

import sqlalchemy
from sqlalchemy.ext.asyncio import AsyncSession

from kmua.config import app_config
from kmua.database.db import with_session, with_tx
from kmua.database.models import Bottle, UserData


@with_tx
async def pick_random_bottle(session: AsyncSession | None = None) -> Bottle | None:
    assert session is not None, "Session must be provided"
    total_bottles = await count_bottles(session)
    if total_bottles == 0:
        return None
    random_offset = random.randint(0, total_bottles - 1)
    random_bottle_stmt = sqlalchemy.select(Bottle).offset(random_offset).limit(1)
    result = await session.execute(random_bottle_stmt)
    bottle = result.scalar_one()
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
async def count_bottles(session: AsyncSession) -> int:
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
