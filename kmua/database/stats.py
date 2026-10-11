"""Aggregate queries for the administrator statistics dashboard."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import sqlalchemy
from sqlalchemy.ext.asyncio import AsyncSession

from .affection import AffectionHistogram
from .db import with_session
from .models import Bottle, BottleReply, ChatData, Quote, UserChatAssociation, UserData

# Width of the "recent activity" window the dashboard shows.
RECENT_DAYS = 7


@with_session
async def get_panel_stats(session: AsyncSession | None = None) -> dict[str, object]:
    """Return every counter the panel dashboard shows, in one session.

    The panel polls this while the dashboard is open, so the cost that matters is
    the number of round trips and table scans rather than how each query reads:
    everything runs on one connection, and `user_data` is scanned once instead of
    once per counter that happens to come from it.

    `recent.*` counts rows created in the last `RECENT_DAYS` days and relies on the
    `created_at` indexes added for exactly these windows.
    """
    assert session is not None
    since = datetime.now(UTC) - timedelta(days=RECENT_DAYS)

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

    async def count_all(model) -> int:
        result = await session.execute(
            sqlalchemy.select(sqlalchemy.func.count()).select_from(model)
        )
        return result.scalar_one()

    async def count_since(model, column) -> int:
        result = await session.execute(
            sqlalchemy.select(sqlalchemy.func.count())
            .select_from(model)
            .where(column >= since)
        )
        return result.scalar_one()

    chats = await count_all(ChatData)
    quotes = await count_all(Quote)
    associations = await count_all(UserChatAssociation)
    bottles = await count_all(Bottle)

    histogram = await session.execute(
        sqlalchemy.select(
            sqlalchemy.func.count(AffectionHistogram.bucket),
            sqlalchemy.func.min(AffectionHistogram.bucket),
            sqlalchemy.func.max(AffectionHistogram.bucket),
        )
    )
    bucket_count, min_bucket, max_bucket = histogram.one()

    interactions = await session.execute(
        sqlalchemy.select(
            sqlalchemy.func.coalesce(sqlalchemy.func.sum(Bottle.picks), 0),
            sqlalchemy.func.coalesce(sqlalchemy.func.sum(Bottle.reports), 0),
        )
    )
    picks, reports = interactions.one()

    recent_chats = await count_since(ChatData, ChatData.created_at)
    recent_quotes = await count_since(Quote, Quote.created_at)
    recent_associations = await count_since(
        UserChatAssociation, UserChatAssociation.created_at
    )
    recent_bottles = await count_since(Bottle, Bottle.created_at)
    recent_replies = await count_since(BottleReply, BottleReply.created_at)

    return {
        "users": users,
        "chats": chats,
        "quotes": quotes,
        "associations": associations,
        "bottles": bottles,
        "affection": {
            "total_users": users,
            "bucket_count": bucket_count,
            "min_bucket": min_bucket,
            "max_bucket": max_bucket,
        },
        "dashboard": {
            "users": users,
            "user_structure": {
                "real_users": real_users,
                "bots": bots,
                "global_admins": global_admins,
                "married_users": married_users,
            },
            "recent": {
                "days": RECENT_DAYS,
                "chats": recent_chats,
                "quotes": recent_quotes,
                "associations": recent_associations,
                "bottles": recent_bottles,
                "bottle_replies": recent_replies,
            },
            "bottle_interactions": {
                "picks": picks,
                "reports": reports,
                "replies": recent_replies,
            },
        },
    }


__all__ = ["get_panel_stats"]
