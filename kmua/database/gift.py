import sqlalchemy
from sqlalchemy.ext.asyncio import AsyncSession

from kmua import gift
from kmua.database.db import with_session, with_tx
from kmua.database.models import Gift, UserData


@with_tx
async def add_gift_to_user(
    owner_id: int,
    gift_id: gift.GiftID,
    session: AsyncSession | None = None,
):
    assert session is not None, "Session must be provided"
    gift_entry = Gift(
        owner_id=owner_id,
        gift_id=gift_id,
        sent_to_bot=False,
    )
    session.add(gift_entry)


@with_session
async def get_user_gifts(
    owner_id: int,
    sent: bool = False,
    offset: int = 0,
    limit: int = 5,
    session: AsyncSession | None = None,
) -> list[Gift]:
    assert session is not None, "Session must be provided"
    result = await session.execute(
        sqlalchemy.select(Gift)
        .where(Gift.owner_id == owner_id)
        .where(Gift.sent_to_bot == sent)
        .offset(offset)
        .limit(limit)
        .order_by(Gift.created_at.desc())
    )
    gifts = result.scalars().all()
    return gifts


@with_tx
async def mark_gift_as_sent(
    gift_db_id: int,
    session: AsyncSession | None = None,
):
    assert session is not None, "Session must be provided"
    stmt = sqlalchemy.update(Gift).where(Gift.id == gift_db_id).values(sent_to_bot=True)
    await session.execute(stmt)


@with_tx
async def buy_gift_for_user(
    owner_id: int,
    gift_id: gift.GiftID,
    session: AsyncSession | None = None,
):
    assert session is not None, "Session must be provided"
    cost = gift.get_gift_by_id(gift_id).price
    user_data = await session.get(UserData, owner_id)
    if user_data is None:
        raise ValueError("User not found")
    config = user_data.user_config
    if config.coins < cost:
        raise ValueError("Not enough coins to buy gift")
    config.coins = max(-144 * 16, config.coins - cost)
    user_data.user_config = config
    await add_gift_to_user(owner_id, gift_id, session=session)


@with_session
async def get_gift_by_db_id(
    gift_db_id: int,
    session: AsyncSession | None = None,
) -> Gift | None:
    assert session is not None, "Session must be provided"
    result = await session.execute(sqlalchemy.select(Gift).where(Gift.id == gift_db_id))
    gift_entry = result.scalar_one_or_none()
    return gift_entry


@with_session
async def count_user_gifts(
    owner_id: int,
    sent: bool = False,
    session: AsyncSession | None = None,
) -> int:
    assert session is not None, "Session must be provided"
    result = await session.execute(
        sqlalchemy.select(sqlalchemy.func.count(Gift.id))
        .where(Gift.owner_id == owner_id)
        .where(Gift.sent_to_bot == sent)
    )
    count = result.scalar_one()
    return count
