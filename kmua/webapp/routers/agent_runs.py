"""Recorded agent runs, read-only.

The panel side of the run trace: which runs exist, what each step did, and - for a
model request - the exact messages the model was given. Writes only ever happen on
the bot's side (`kmua.plugins.agent.trace`), so nothing here mutates a trace: a
record read by an operator must stay what the bot actually did.

Owner-only, unlike the rest of the panel: every other endpoint at the admin tier
returns records and counters, while these return conversation content - private
chats included, and the transcript the model was given.

The kind and status vocabularies are spelled out as `Literal`s so FastAPI and the
OpenAPI schema enforce them and an unknown value is a 422 rather than an empty
page; the trailing check keeps them honest against the storage module, which owns
the authoritative tuples.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal, get_args

from fastapi import APIRouter, Path, Query

from kmua.database import agent_trace as store
from kmua.webapp.deps import RequireOwner
from kmua.webapp.errors import ErrorCode, not_found
from kmua.webapp.schemas import (
    AgentRunDetailOut,
    AgentRunEventDetailOut,
    AgentRunOut,
    PageOut,
)
from kmua.webapp.serializers import (
    agent_run_detail_out,
    agent_run_event_detail_out,
    agent_run_out,
)

router = APIRouter(prefix="/api/admin/agent-runs", tags=["admin"])

AgentRunKind = Literal[
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
]

AgentRunStatus = Literal["ok", "error", "timeout", "cancelled", "rejected"]

if (
    tuple(get_args(AgentRunKind)) != store.RUN_KINDS
    or tuple(get_args(AgentRunStatus)) != store.RUN_STATUSES
):
    raise RuntimeError(
        "agent run vocabulary in kmua.webapp.routers.agent_runs drifted from "
        "kmua.database.agent_trace"
    )

KindQuery = Annotated[AgentRunKind | None, Query(description="Run category")]
StatusQuery = Annotated[AgentRunStatus | None, Query(description="How the run ended")]


def _as_utc(value: datetime | None) -> datetime | None:
    """Read a caller-supplied instant as UTC, whatever offset it carries.

    Rows are stamped with UTC instants, but the two backends would read a naive
    value differently (SQLite binds wall-clock fields, Postgres starts from the
    host's zone), so a hand-made request would filter a different window per
    deployment. The panel always sends an absolute instant; this makes that the
    rule rather than the caller's habit.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@router.get("", response_model=PageOut[AgentRunOut])
async def list_agent_runs(
    user: RequireOwner,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    session_id: str | None = Query(
        None, max_length=32, description="Session id, or part of it"
    ),
    chat_id: int | None = Query(None),
    user_id: int | None = Query(None),
    kind: KindQuery = None,
    status: StatusQuery = None,
    q: str = Query("", max_length=128),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
) -> PageOut[AgentRunOut]:
    """Runs, newest first, filtered by session, identity, category, outcome or time."""
    result = await store.get_runs_page(
        page=page,
        size=size,
        session_id=session_id,
        chat_id=chat_id,
        user_id=user_id,
        kind=kind,
        status=status,
        query=q,
        since=_as_utc(since),
        until=_as_utc(until),
    )
    return PageOut(
        items=[agent_run_out(run) for run in result.items],
        total=result.total,
        page=result.page,
        size=result.size,
    )


@router.get("/{run_id}", response_model=AgentRunDetailOut)
async def read_agent_run(user: RequireOwner, run_id: int) -> AgentRunDetailOut:
    run = await store.get_run(run_id)
    if run is None:
        raise not_found(ErrorCode.NOT_FOUND, "Agent run not found")
    events = await store.list_run_events(run_id)
    return agent_run_detail_out(run, events)


@router.get("/{run_id}/events/{seq}", response_model=AgentRunEventDetailOut)
async def read_agent_run_event(
    user: RequireOwner,
    run_id: int,
    seq: int = Path(ge=1, description="Step number within the run"),
) -> AgentRunEventDetailOut:
    """One step in full: its payload, and a request's replayed messages."""
    event = await store.get_run_event(run_id, seq)
    if event is None:
        raise not_found(ErrorCode.NOT_FOUND, "Agent run event not found")
    messages = (
        await store.reconstruct_request_messages(run_id, seq)
        if event.kind == "model_request"
        else None
    )
    return agent_run_event_detail_out(event, messages)
