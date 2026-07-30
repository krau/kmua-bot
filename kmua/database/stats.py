"""Aggregate queries for the administrator statistics dashboard."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import sqlalchemy
from sqlalchemy.ext.asyncio import AsyncSession

from .db import with_session
from .models import Bottle, BottleReply, ChatData, Quote, UserChatAssociation, UserData


@with_session
async def get_dashboard_stats(session: AsyncSession | None = None) -> dict[str, object]:
    """Return bounded aggregate facts without loading individual records."""
    assert session is not None
    since = datetime.now(UTC) - timedelta(days=7)

    totals = await session.execute(
        sqlalchemy.select(
            sqlalchemy.func.count(UserData.id),
            sqlalchemy.func.count(UserData.id).filter(UserData.is_real_user),
            sqlalchemy.func.count(UserData.id).filter(UserData.is_bot),
            sqlalchemy.func.count(UserData.id).filter(UserData.is_bot_global_admin),
            sqlalchemy.func.count(UserData.id).filter(UserData.is_married),
        )
    )
    users, real_users, bots, global_admins, married_users = totals.one()

    async def count_since(model, column) -> int:
        result = await session.execute(
            sqlalchemy.select(sqlalchemy.func.count()).select_from(model).where(column >= since)
        )
        return result.scalar_one()

    chats = await count_since(ChatData, ChatData.created_at)
    quotes = await count_since(Quote, Quote.created_at)
    associations = await count_since(UserChatAssociation, UserChatAssociation.created_at)
    bottles = await count_since(Bottle, Bottle.created_at)
    replies = await count_since(BottleReply, BottleReply.created_at)
    bottle_interactions = await session.execute(
        sqlalchemy.select(
            sqlalchemy.func.coalesce(sqlalchemy.func.sum(Bottle.picks), 0),
            sqlalchemy.func.coalesce(sqlalchemy.func.sum(Bottle.reports), 0),
        )
    )
    picks, reports = bottle_interactions.one()

    return {
        "users": users,
        "user_structure": {
            "real_users": real_users,
            "bots": bots,
            "global_admins": global_admins,
            "married_users": married_users,
        },
        "recent": {
            "days": 7,
            "chats": chats,
            "quotes": quotes,
            "associations": associations,
            "bottles": bottles,
            "bottle_replies": replies,
        },
        "bottle_interactions": {"picks": picks, "reports": reports, "replies": replies},
    }


__all__ = ["get_dashboard_stats"]
