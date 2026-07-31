"""RSS/Atom subscription storage.

Two concerns, deliberately separated from each other:

1. Deduplication. A feed is a row in `rss_feeds`, shared by however many chats
   subscribe to it, so the poll job fetches each URL once and fans out. A chat's
   subscription (`rss_subscriptions`) is a thin join row on top of that.
2. Whitelisting. `rss_allowed` is a `ChatPolicy` flag (JSON column, no migration):
   when `rss_whitelist_mode` is on, only chats the owner has explicitly allowed may
   subscribe at all. Unlike the agent flag, RSS checks all happen in async contexts
   (command handlers, HTTP endpoints), so there is no in-memory mirror here — the DB
   is read directly, and `is_rss_allowed` is deliberately NOT a `chat_policy.py`
   mirror getter.
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy
import sqlalchemy.orm
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from kmua.config import app_config
from kmua.database import pagination
from kmua.database.db import with_session, with_tx
from kmua.database.models import ChatPolicyData, RssFeed, RssSubscription

MAX_FEEDS_PER_CHAT = 20
"""Per-chat cap. Guards against one chat turning the poll job into a crawler."""

MAX_SEEN_IDS = 200
"""How many entry ids to remember per feed. Comfortably above any feed's page size,
so an entry cannot fall out of the window and be re-pushed as new."""

MIN_SUBSCRIPTION_INTERVAL = 1
MAX_SUBSCRIPTION_INTERVAL = 1440
"""Per-subscription poll interval bounds, in minutes. None means global."""


@with_session
async def is_rss_allowed(chat_id: int, session: AsyncSession | None = None) -> bool:
    """Whether this chat may use RSS at all.

    Reads the `rss_allowed` policy flag. Returns True unconditionally when
    `app_config.rss_whitelist_mode` is off, matching `is_chat_allowed`'s shape.
    """
    assert session is not None

    if not app_config.rss_whitelist_mode:
        return True

    row = await session.get(ChatPolicyData, chat_id)
    return row.chat_policy.rss_allowed if row else False


@with_tx
async def get_or_create_feed(url: str, session: AsyncSession | None = None) -> RssFeed:
    """The feed row for `url`, inserted if absent. Dedupes by exact URL."""
    assert session is not None

    row = await get_feed_by_url(url, session=session)
    if row is not None:
        return row

    feed = RssFeed(url=url)
    session.add(feed)
    await session.flush()
    return feed


@with_session
async def get_feed_by_url(
    url: str, session: AsyncSession | None = None
) -> RssFeed | None:
    assert session is not None

    stmt = sqlalchemy.select(RssFeed).where(RssFeed.url == url)
    return (await session.execute(stmt)).scalar_one_or_none()


@with_session
async def get_feed_by_id(
    feed_id: int, session: AsyncSession | None = None
) -> RssFeed | None:
    assert session is not None

    return await session.get(RssFeed, feed_id)


@with_tx
async def add_subscription(
    chat_id: int,
    url: str,
    *,
    created_by: int | None = None,
    session: AsyncSession | None = None,
) -> tuple[RssSubscription | None, str | None]:
    """Subscribe `chat_id` to `url`.

    Returns `(subscription, None)` on success, or `(None, reason)` where reason is
    exactly one of the literals "already_subscribed" or "limit_reached". Returning a
    reason rather than raising keeps the command handler and the HTTP endpoint able to
    map the same outcome onto their own vocabularies.
    """
    assert session is not None

    if await count_chat_subscriptions(chat_id, session=session) >= MAX_FEEDS_PER_CHAT:
        return None, "limit_reached"

    try:
        feed = await get_or_create_feed(url, session=session)
        existing = (
            await session.execute(
                sqlalchemy.select(RssSubscription).where(
                    RssSubscription.chat_id == chat_id,
                    RssSubscription.feed_id == feed.id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return None, "already_subscribed"

        sub = RssSubscription(chat_id=chat_id, feed_id=feed.id, created_by=created_by)
        session.add(sub)
        await session.flush()
    except IntegrityError:
        # Two interleaved adds (same URL from two chats, or a double tap) can
        # both pass the select and one flush hits the unique constraints. The
        # row the other caller created is exactly what this caller wanted.
        await session.rollback()
        return None, "already_subscribed"

    # Re-select with the feed joined: `lazy="joined"` applies to queries, not to a
    # freshly flushed row, and callers serialize `sub.feed` after this session is
    # closed.
    loaded = (
        await session.execute(
            sqlalchemy.select(RssSubscription)
            .options(sqlalchemy.orm.joinedload(RssSubscription.feed))
            .where(RssSubscription.id == sub.id)
        )
    ).scalar_one()
    return loaded, None


@with_tx
async def remove_subscription(
    chat_id: int, feed_id: int, session: AsyncSession | None = None
) -> bool:
    """Unsubscribe. False when the chat had no such subscription.

    Also deletes the feed row when this was its last subscriber, so an unsubscribed
    feed stops being polled instead of lingering forever.
    """
    assert session is not None

    sub = (
        await session.execute(
            sqlalchemy.select(RssSubscription).where(
                RssSubscription.chat_id == chat_id,
                RssSubscription.feed_id == feed_id,
            )
        )
    ).scalar_one_or_none()
    if sub is None:
        return False

    await session.delete(sub)
    await session.flush()

    remaining = (
        await session.execute(
            sqlalchemy.select(sqlalchemy.func.count())
            .select_from(RssSubscription)
            .where(RssSubscription.feed_id == feed_id)
        )
    ).scalar() or 0
    if remaining == 0:
        feed = await session.get(RssFeed, feed_id)
        if feed is not None:
            await session.delete(feed)
    await session.flush()
    return True


@with_tx
async def set_subscription_paused(
    chat_id: int, feed_id: int, paused: bool, session: AsyncSession | None = None
) -> bool:
    """Pause/resume. False when the chat had no such subscription."""
    assert session is not None

    sub = (
        await session.execute(
            sqlalchemy.select(RssSubscription).where(
                RssSubscription.chat_id == chat_id,
                RssSubscription.feed_id == feed_id,
            )
        )
    ).scalar_one_or_none()
    if sub is None:
        return False

    sub.paused = paused
    await session.flush()
    return True


@with_session
async def get_chat_subscriptions(
    chat_id: int, session: AsyncSession | None = None
) -> list[RssSubscription]:
    """Every subscription for one chat, newest first. Feed eagerly loaded."""
    assert session is not None

    stmt = (
        sqlalchemy.select(RssSubscription)
        .options(sqlalchemy.orm.joinedload(RssSubscription.feed))
        .where(RssSubscription.chat_id == chat_id)
        .order_by(RssSubscription.created_at.desc(), RssSubscription.id.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


@with_session
async def get_chat_subscriptions_paged(
    chat_id: int,
    *,
    page: int = 1,
    size: int = pagination.DEFAULT_PAGE_SIZE,
    session: AsyncSession | None = None,
) -> pagination.Page[RssSubscription]:
    """Paged variant for the panel. Uses `pagination.normalize_page`/`offset_for`."""
    assert session is not None

    page, size = pagination.normalize_page(page, size)

    total = (
        await session.execute(
            sqlalchemy.select(sqlalchemy.func.count())
            .select_from(RssSubscription)
            .where(RssSubscription.chat_id == chat_id)
        )
    ).scalar() or 0

    stmt = (
        sqlalchemy.select(RssSubscription)
        .options(sqlalchemy.orm.joinedload(RssSubscription.feed))
        .where(RssSubscription.chat_id == chat_id)
        .order_by(RssSubscription.created_at.desc(), RssSubscription.id.desc())
        .offset(pagination.offset_for(page, size))
        .limit(size)
    )
    items = (await session.execute(stmt)).scalars().all()
    return pagination.Page(items=items, total=total, page=page, size=size)


@with_session
async def count_chat_subscriptions(
    chat_id: int, session: AsyncSession | None = None
) -> int:
    assert session is not None

    stmt = (
        sqlalchemy.select(sqlalchemy.func.count())
        .select_from(RssSubscription)
        .where(RssSubscription.chat_id == chat_id)
    )
    return (await session.execute(stmt)).scalar() or 0


@with_session
async def get_active_feeds(
    session: AsyncSession | None = None,
) -> list[tuple[RssFeed, int]]:
    """Feeds to poll, each with its effective interval in minutes.

    A feed with at least one unpaused subscription is active; a feed whose every
    subscription is paused is skipped entirely: fetching bytes nobody will
    receive is pure waste.

    The effective interval is the minimum across the feed's unpaused
    subscriptions (subscription-level minutes, else the global `rss_interval`)
    - the subscriber who wants the fastest cadence sets the pace.
    """
    assert session is not None

    global_minutes = app_config.rss_interval
    effective = sqlalchemy.func.min(
        sqlalchemy.func.coalesce(RssSubscription.interval_minutes, global_minutes)
    )
    # `GROUP BY rss_feeds.id` already yields one row per feed; the extra
    # `.distinct()` is not just redundant - on PostgreSQL `SELECT DISTINCT`
    # compares the whole result row for equality, and `json` columns have no
    # equality operator (jsonb does, json does not), so the query fails with
    # "could not identify an equality operator for type json".
    stmt = (
        sqlalchemy.select(RssFeed, effective)
        .join(RssSubscription, RssSubscription.feed_id == RssFeed.id)
        .where(RssSubscription.paused.is_(False))
        .group_by(RssFeed.id)
    )
    rows = (await session.execute(stmt)).all()
    return [(feed, int(minutes)) for feed, minutes in rows]


@with_session
async def get_feed_target_chats(
    feed_id: int, session: AsyncSession | None = None
) -> list[int]:
    """Chat ids to deliver this feed to: unpaused subscriptions only."""
    assert session is not None

    stmt = (
        sqlalchemy.select(RssSubscription.chat_id)
        .where(
            RssSubscription.feed_id == feed_id,
            RssSubscription.paused.is_(False),
        )
        .order_by(RssSubscription.chat_id)
    )
    return list((await session.execute(stmt)).scalars().all())


@with_tx
async def record_fetch_success(
    feed_id: int,
    *,
    title: str | None,
    etag: str | None,
    last_modified: str | None,
    seen_entry_ids: list[str],
    session: AsyncSession | None = None,
) -> None:
    """Commit post-fetch state: clears `last_error`, zeroes `failure_count`, sets
    `last_fetched_at` to `datetime.now(UTC)`, and replaces `seen_entry_ids` with the
    last `MAX_SEEN_IDS` ids. `title` only overwrites when non-empty."""
    assert session is not None

    feed = await session.get(RssFeed, feed_id)
    if feed is None:
        return

    if title:
        feed.title = title
    feed.etag = etag
    feed.last_modified = last_modified
    feed.seen_entry_ids = seen_entry_ids[-MAX_SEEN_IDS:]
    feed.last_error = None
    feed.failure_count = 0
    feed.last_fetched_at = datetime.now(UTC)
    await session.flush()


@with_tx
async def record_fetch_failure(
    feed_id: int, error: str, session: AsyncSession | None = None
) -> None:
    """Increment `failure_count`, store `error` truncated to 512 chars, and set
    `last_fetched_at`."""
    assert session is not None

    feed = await session.get(RssFeed, feed_id)
    if feed is None:
        return

    feed.failure_count += 1
    feed.last_error = error[:512]
    feed.last_fetched_at = datetime.now(UTC)
    await session.flush()


@with_tx
async def set_subscription_interval(
    chat_id: int,
    feed_id: int,
    minutes: int | None,
    session: AsyncSession | None = None,
) -> bool:
    """Set one subscription's poll interval, in minutes; None = global default.

    False when the chat had no such subscription.
    """
    assert session is not None

    sub = (
        await session.execute(
            sqlalchemy.select(RssSubscription).where(
                RssSubscription.chat_id == chat_id,
                RssSubscription.feed_id == feed_id,
            )
        )
    ).scalar_one_or_none()
    if sub is None:
        return False

    sub.interval_minutes = minutes
    await session.flush()
    return True


@with_tx
async def touch_fetch(feed_id: int, session: AsyncSession | None = None) -> None:
    """Record that a poll happened without changing feed state (a 304).

    Keeps the per-feed cadence honest: a not-modified response is still a fetch,
    and without the timestamp bump the next tick would immediately re-request.
    """
    assert session is not None

    feed = await session.get(RssFeed, feed_id)
    if feed is None:
        return
    feed.last_fetched_at = datetime.now(UTC)
    await session.flush()


@with_tx
async def delete_chat_subscriptions(
    chat_id: int, session: AsyncSession | None = None
) -> int:
    """Drop every subscription for a chat, returning the count. Called when the bot
    is kicked or the push job hits an unrecoverable delivery error."""
    assert session is not None

    stmt = sqlalchemy.delete(RssSubscription).where(RssSubscription.chat_id == chat_id)
    result = await session.execute(stmt)
    await session.flush()
    # `execute` on a DELETE is a CursorResult at runtime; pyright cannot see that
    # through the generic `Result` return annotation.
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


__all__ = [
    "MAX_FEEDS_PER_CHAT",
    "MAX_SEEN_IDS",
    "MIN_SUBSCRIPTION_INTERVAL",
    "MAX_SUBSCRIPTION_INTERVAL",
    "add_subscription",
    "count_chat_subscriptions",
    "delete_chat_subscriptions",
    "get_active_feeds",
    "get_chat_subscriptions",
    "get_chat_subscriptions_paged",
    "get_feed_by_id",
    "get_feed_by_url",
    "get_feed_target_chats",
    "get_or_create_feed",
    "is_rss_allowed",
    "record_fetch_failure",
    "record_fetch_success",
    "remove_subscription",
    "set_subscription_interval",
    "set_subscription_paused",
    "touch_fetch",
]
