"""Agent run traces: what each run sent, what it got back, and how it went.

One `agent_runs` row per run plus one `agent_run_events` row per step. Both are
append-only and written once, when the run ends: a run that never finished leaves
no row, so a trace can never describe a half-executed turn.

Runs carry the conversation instance they belong to in `session_id` - the id
`kmua.plugins.agent.state` hands out per (chat, user) thread. Nested runs inherit
their parent's, and the bot's own work (RSS, sticker descriptions) has none.

The enumerated string values live here as module constants because the write side
(`kmua.plugins.agent.trace`) and the read side (`kmua.webapp.routers.agent_runs`)
both validate against them; the tables themselves carry no enum constraint, like
every other string column in this schema.

`model_request` payloads are an increment over the previous request of the same
conversation: the messages past their longest common prefix, and the instructions
only when those changed. `messages_total` and `messages_prefix_len` say where the
increment starts, so reading a whole request means replaying the conversation in
order; the panel shows the increment itself.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import sqlalchemy
from sqlalchemy.ext.asyncio import AsyncSession

from . import pagination
from .db import with_session, with_tx
from .models import AgentRun, AgentRunEvent

RUN_KINDS: tuple[str, ...] = (
    "chat",
    "ask",
    "followup",
    "followup_relevance",
    "channel_comment",
    "rss_digest",
    "rss_broadcast",
    "sticker_description",
    "memory",
    "transcription",
    "compaction",
)

RUN_STATUSES: tuple[str, ...] = ("ok", "error", "timeout", "cancelled", "rejected")

REJECT_REASONS: tuple[str, ...] = ("quota", "whitelist")

EVENT_KINDS: tuple[str, ...] = (
    "model_request",
    "model_response",
    "tool_call",
    "tool_result",
    "steering",
    "error",
)

# A payload replaced by one of these markers is gone, so a request whose data was
# dropped this way cannot be replayed. The reasons are the two caps in
# `kmua.plugins.agent.trace`.
PAYLOAD_CAP_REASONS: frozenset[str] = frozenset(
    {"event_payload_cap", "run_payload_cap"}
)


@dataclass(slots=True)
class AgentRunEventDraft:
    """One event, ready to insert. `seq` is 1-based and assigned by the caller."""

    seq: int
    kind: str
    status: str = "ok"
    name: str | None = None
    duration_ms: int | None = None
    payload: dict[str, Any] | None = None
    payload_chars: int | None = None
    truncated: bool = False


@dataclass(slots=True)
class AgentRunDraft:
    """One run, ready to insert.

    `events` holds this run's own steps and `children` the runs nested inside it;
    `event_count` is not carried here because it is exactly `len(events)` and two
    sources for one number is one too many.
    """

    kind: str
    status: str
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    events: tuple[AgentRunEventDraft, ...] = ()
    children: tuple[AgentRunDraft, ...] = ()
    events_dropped: int = 0
    reject_reason: str | None = None
    session_id: str | None = None
    chat_id: int | None = None
    user_id: int | None = None
    message_id: int | None = None
    parent_run_id: int | None = None
    model_name: str | None = None
    model_role: str | None = None
    streaming: bool = False
    requests: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    output_kind: str | None = None
    output_text: str | None = None
    output_chars: int | None = None
    error_class: str | None = None
    error_message: str | None = None


def _run_values(draft: AgentRunDraft, parent_run_id: int | None) -> dict[str, Any]:
    return {
        "kind": draft.kind,
        "status": draft.status,
        "reject_reason": draft.reject_reason,
        "session_id": draft.session_id,
        "chat_id": draft.chat_id,
        "user_id": draft.user_id,
        "message_id": draft.message_id,
        "parent_run_id": parent_run_id,
        "model_name": draft.model_name,
        "model_role": draft.model_role,
        "streaming": draft.streaming,
        "started_at": draft.started_at,
        "finished_at": draft.finished_at,
        "duration_ms": draft.duration_ms,
        "requests": draft.requests,
        "tool_calls": draft.tool_calls,
        "input_tokens": draft.input_tokens,
        "output_tokens": draft.output_tokens,
        "cache_read_tokens": draft.cache_read_tokens,
        "cache_write_tokens": draft.cache_write_tokens,
        "output_kind": draft.output_kind,
        "output_text": draft.output_text,
        "output_chars": draft.output_chars,
        "error_class": draft.error_class,
        "error_message": draft.error_message,
        "event_count": len(draft.events),
        "events_dropped": draft.events_dropped,
    }


async def _insert_run(
    session: AsyncSession, draft: AgentRunDraft, parent_run_id: int | None
) -> int:
    """Insert one run and its subtree, parents before children.

    The parent's id only exists after the flush, which is why children are walked
    after it rather than built alongside it.
    """
    run = AgentRun(**_run_values(draft, parent_run_id))
    session.add(run)
    await session.flush()

    for event in draft.events:
        session.add(
            AgentRunEvent(
                run_id=run.id,
                seq=event.seq,
                kind=event.kind,
                name=event.name,
                status=event.status,
                duration_ms=event.duration_ms,
                payload=event.payload,
                payload_chars=event.payload_chars,
                truncated=event.truncated,
            )
        )

    for child in draft.children:
        await _insert_run(session, child, run.id)

    return run.id


@with_tx
async def record_trace(
    drafts: Sequence[AgentRunDraft], session: AsyncSession | None = None
) -> None:
    """Write runs and their events in one transaction, parents first."""
    assert session is not None
    for draft in drafts:
        await _insert_run(session, draft, draft.parent_run_id)


@with_tx
async def record_rejection(
    draft: AgentRunDraft, session: AsyncSession | None = None
) -> None:
    """Write a single refusal row; refused runs have no events by construction."""
    assert session is not None
    await _insert_run(session, draft, draft.parent_run_id)


@with_session
async def get_runs_page(
    page: int = 1,
    size: int = pagination.DEFAULT_PAGE_SIZE,
    *,
    session_id: str | None = None,
    chat_id: int | None = None,
    user_id: int | None = None,
    kind: str | None = None,
    status: str | None = None,
    query: str = "",
    since: datetime | None = None,
    until: datetime | None = None,
    session: AsyncSession | None = None,
) -> pagination.Page[AgentRun]:
    """List runs, newest first, with the panel's filters applied."""
    assert session is not None

    page, size = pagination.normalize_page(page, size)
    conditions = []
    if session_id:
        # Substring, like the text search: an operator reads the first characters of
        # an id off the list and pastes those back.
        conditions.append(pagination.text_match(AgentRun.session_id, session_id))
    if chat_id is not None:
        conditions.append(AgentRun.chat_id == chat_id)
    if user_id is not None:
        conditions.append(AgentRun.user_id == user_id)
    if kind:
        conditions.append(AgentRun.kind == kind)
    if status:
        conditions.append(AgentRun.status == status)
    if since is not None:
        conditions.append(AgentRun.started_at >= since)
    if until is not None:
        conditions.append(AgentRun.started_at <= until)
    query = query.strip()
    if query:
        conditions.append(
            sqlalchemy.or_(
                pagination.text_match(AgentRun.output_text, query),
                pagination.text_match(AgentRun.error_message, query),
            )
        )

    total_stmt = sqlalchemy.select(sqlalchemy.func.count()).select_from(AgentRun)
    if conditions:
        total_stmt = total_stmt.where(*conditions)
    total = (await session.execute(total_stmt)).scalar() or 0

    stmt = sqlalchemy.select(AgentRun)
    if conditions:
        stmt = stmt.where(*conditions)
    stmt = (
        stmt.order_by(AgentRun.started_at.desc(), AgentRun.id.desc())
        .offset(pagination.offset_for(page, size))
        .limit(size)
    )
    items = (await session.execute(stmt)).scalars().all()
    return pagination.Page(items=items, total=total, page=page, size=size)


@with_session
async def get_run(run_id: int, session: AsyncSession | None = None) -> AgentRun | None:
    """One run, or None when the id is unknown."""
    assert session is not None
    return (
        await session.execute(sqlalchemy.select(AgentRun).where(AgentRun.id == run_id))
    ).scalar_one_or_none()


@with_session
async def list_run_events(
    run_id: int, session: AsyncSession | None = None
) -> list[AgentRunEvent]:
    """Every event of one run, in the order the run produced them."""
    assert session is not None
    stmt = (
        sqlalchemy.select(AgentRunEvent)
        .where(AgentRunEvent.run_id == run_id)
        .order_by(AgentRunEvent.seq)
    )
    return list((await session.execute(stmt)).scalars().all())


@with_session
async def get_run_event(
    run_id: int, seq: int, session: AsyncSession | None = None
) -> AgentRunEvent | None:
    """One event by position, or None when the run has no such step."""
    assert session is not None
    stmt = sqlalchemy.select(AgentRunEvent).where(
        AgentRunEvent.run_id == run_id, AgentRunEvent.seq == seq
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def _payload_of(event: AgentRunEvent) -> dict[str, Any] | None:
    payload = event.payload
    return payload if isinstance(payload, dict) else None


@with_tx
async def delete_runs_before(
    cutoff: datetime, session: AsyncSession | None = None
) -> int:
    """Delete runs started before `cutoff` and their events; returns the run count.

    A run that belongs to a conversation is only deleted once the whole conversation
    is older than the cutoff: its records are increments of one another, so the newer
    ones are unreadable without the older ones and there is nothing to rebuild them
    from. A run with no conversation is on its own and goes by age.

    Both deletes happen here rather than through `ON DELETE CASCADE`: SQLite in
    this project never enables `PRAGMA foreign_keys`, and the tables declare no
    foreign keys anyway.
    """
    assert session is not None
    idle_sessions = (
        sqlalchemy.select(AgentRun.session_id)
        .where(AgentRun.session_id.is_not(None))
        .group_by(AgentRun.session_id)
        .having(sqlalchemy.func.max(AgentRun.started_at) < cutoff)
    )
    # One statement picks the runs to drop, then both tables are emptied by id: the
    # selection cannot shift between the two deletes, and the caller's count is what
    # the selection found rather than what each delete happened to touch.
    expired = list(
        (
            await session.execute(
                sqlalchemy.select(AgentRun.id).where(
                    sqlalchemy.or_(
                        sqlalchemy.and_(
                            AgentRun.session_id.is_(None), AgentRun.started_at < cutoff
                        ),
                        AgentRun.session_id.in_(idle_sessions),
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    if not expired:
        return 0
    await session.execute(
        sqlalchemy.delete(AgentRunEvent).where(AgentRunEvent.run_id.in_(expired))
    )
    await session.execute(sqlalchemy.delete(AgentRun).where(AgentRun.id.in_(expired)))
    return len(expired)


@with_session
async def session_has_stored_requests(
    session_id: str, session: AsyncSession | None = None
) -> bool:
    """Whether one conversation already has a request on record.

    The capture side asks before it decides what to store: a conversation whose
    records were cleaned up has nothing left to increment, so its next request has
    to be written whole.
    """
    assert session is not None
    stmt = (
        sqlalchemy.select(AgentRunEvent.id)
        .join(AgentRun, AgentRun.id == AgentRunEvent.run_id)
        .where(
            AgentRun.session_id == session_id,
            AgentRunEvent.kind == "model_request",
        )
        .limit(1)
    )
    return (await session.execute(stmt)).first() is not None


__all__ = [
    "EVENT_KINDS",
    "PAYLOAD_CAP_REASONS",
    "REJECT_REASONS",
    "RUN_KINDS",
    "RUN_STATUSES",
    "AgentRunDraft",
    "AgentRunEventDraft",
    "delete_runs_before",
    "get_run",
    "get_run_event",
    "get_runs_page",
    "list_run_events",
    "record_rejection",
    "record_trace",
    "session_has_stored_requests",
]
