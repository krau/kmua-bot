"""Agent run tracing: what the capture layer stores, and how it reads back.

The trace is a diagnostic record, so these tests defend two things at once: that a
finished run lands in the database with its events intact, and that the compact
encoding of request messages can be replayed into exactly what the model received.
"""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pyrogram.enums
import pytest
import sqlalchemy
from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import (
    ImageUrl,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RunUsage

from kmua import database
from kmua.common.memory_store import memttlcache
from kmua.config import app_config
from kmua.database import agent_trace as dao
from kmua.database.db import AsyncSessionFactory
from kmua.database.models import AgentRun, AgentRunEvent
from kmua.plugins.agent import quota, runner, state, trace

pytestmark = pytest.mark.usefixtures("initialised_db")


@pytest.fixture(autouse=True)
async def clean_traces():
    """Start every test from empty trace tables: runs are append-only."""
    async with AsyncSessionFactory() as session:
        async with session.begin():
            await session.execute(sqlalchemy.delete(AgentRunEvent))
            await session.execute(sqlalchemy.delete(AgentRun))
    yield


async def runs() -> list[AgentRun]:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            sqlalchemy.select(AgentRun).order_by(AgentRun.id)
        )
        return list(result.scalars().all())


async def stored_events(run_id: int) -> list[AgentRunEvent]:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            sqlalchemy.select(AgentRunEvent)
            .where(AgentRunEvent.run_id == run_id)
            .order_by(AgentRunEvent.seq)
        )
        return list(result.scalars().all())


async def wait_for_runs(count: int, timeout: float = 5.0) -> list[AgentRun]:
    """Wait for the background write; the capture path never blocks its caller."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        rows = await runs()
        if len(rows) >= count:
            return rows
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"expected {count} run row(s), saw {len(rows)}")
        await asyncio.sleep(0.02)


# ------------------------------------------------------------------ write path


async def test_a_finished_run_lands_with_its_events_in_order():
    session = await trace.start_trace("chat", chat_id=-100, user_id=7, message_id=42)
    assert session is not None
    session.note_steering(["wait", "actually"])
    session.note_tool_call(
        ToolCallPart(tool_name="echo", args={"text": "hi"}, tool_call_id="c1"),
        {"text": "hi"},
    )

    task = trace.finish_trace(
        session,
        usage=RunUsage(input_tokens=120, output_tokens=30, requests=2, tool_calls=1),
        output="done",
        model_name="test-model",
        model_role="main",
    )
    assert task is not None
    await task

    rows = await runs()
    assert len(rows) == 1
    run = rows[0]
    assert (run.kind, run.status) == ("chat", "ok")
    assert (run.chat_id, run.user_id, run.message_id) == (-100, 7, 42)
    assert run.model_name == "test-model" and run.model_role == "main"
    assert (run.requests, run.tool_calls) == (2, 1)
    assert (run.input_tokens, run.output_tokens) == (120, 30)
    assert (run.output_kind, run.output_text, run.output_chars) == ("str", "done", 4)
    assert run.error_class is None
    assert run.parent_run_id is None
    assert (run.event_count, run.events_dropped) == (2, 0)
    assert run.duration_ms >= 0

    events = await stored_events(run.id)
    assert [event.seq for event in events] == [1, 2]
    assert [event.kind for event in events] == ["steering", "tool_call"]
    assert events[0].payload == {"texts": ["wait", "actually"]}
    assert events[0].status == "ok"
    assert events[1].name == "echo"
    assert events[1].payload == {"tool_call_id": "c1", "args": {"text": "hi"}}


async def test_a_run_without_a_result_is_recorded_as_incomplete():
    session = await trace.start_trace("chat")
    assert session is not None
    task = trace.finish_trace(session)
    assert task is not None
    await task

    run = (await runs())[0]
    assert run.status == "error"
    assert run.error_class == "AgentRunIncomplete"


async def test_an_explicit_status_wins_over_the_inferred_one():
    session = await trace.start_trace("chat")
    assert session is not None
    task = trace.finish_trace(session, status="cancelled", output=None)
    assert task is not None
    await task
    assert (await runs())[0].status == "cancelled"


async def test_a_nested_run_is_written_under_its_parent():
    parent = await trace.start_trace("chat", chat_id=-100)
    child = await trace.start_trace("compaction")
    assert child is not None and child.parent is parent
    child_task = trace.finish_trace(child, output="summary")
    # The child does not write on its own: the parent's flush carries both.
    assert child_task is None

    parent_task = trace.finish_trace(parent, output="answer")
    assert parent_task is not None
    await parent_task

    rows = await runs()
    assert len(rows) == 2
    by_kind = {row.kind: row for row in rows}
    assert by_kind["compaction"].parent_run_id == by_kind["chat"].id
    assert by_kind["chat"].parent_run_id is None


async def test_long_strings_are_cut_and_the_event_records_it(monkeypatch):
    monkeypatch.setattr(app_config, "agent_trace_max_field_chars", 10, raising=False)
    session = await trace.start_trace("chat")
    assert session is not None
    session.note_steering(["x" * 50])
    task = trace.finish_trace(session, output="ok")
    assert task is not None
    await task

    event = (await stored_events((await runs())[0].id))[0]
    assert event.payload == {"texts": ["x" * 10]}
    # The character count is the pre-truncation size, so the loss is visible.
    assert event.payload_chars is not None and event.payload_chars > 10
    assert event.truncated is True


async def test_event_count_is_capped_and_the_overflow_is_counted():
    session = await trace.start_trace("chat")
    assert session is not None
    for index in range(205):
        session.note_steering([f"message {index}"])
    task = trace.finish_trace(session, output="ok")
    assert task is not None
    await task

    run = (await runs())[0]
    assert run.event_count == 200
    assert run.events_dropped == 5
    assert len(await stored_events(run.id)) == 200
    # Sequence numbers stay dense, so the panel never shows a gap it cannot explain.
    assert [event.seq for event in await stored_events(run.id)][-1] == 200


async def test_an_oversized_payload_becomes_a_marker(monkeypatch):
    monkeypatch.setattr(trace, "_MAX_EVENT_PAYLOAD_CHARS", 100, raising=False)
    session = await trace.start_trace("chat")
    assert session is not None
    session.note_steering(["y" * 500])
    task = trace.finish_trace(session, output="ok")
    assert task is not None
    await task

    event = (await stored_events((await runs())[0].id))[0]
    assert isinstance(event.payload, dict)
    assert event.payload["truncated"] is True
    assert event.payload["reason"] == "event_payload_cap"
    assert event.payload["chars"] > 100
    assert event.truncated is True


async def test_the_run_payload_budget_is_spent_across_events(monkeypatch):
    session = await trace.start_trace("chat")
    assert session is not None
    session.note_steering(["z" * 200])
    session.note_steering(["z" * 200])
    task = trace.finish_trace(session, output="ok")
    assert task is not None
    # Shrunk after both events were buffered: only the flush applies the run cap, and
    # it must admit the first payload while refusing the one that no longer fits.
    monkeypatch.setattr(trace, "_MAX_RUN_PAYLOAD_CHARS", 300, raising=False)
    await task

    first, second = await stored_events((await runs())[0].id)
    assert first.payload == {"texts": ["z" * 200]}
    assert first.truncated is False
    assert isinstance(second.payload, dict)
    assert second.payload["reason"] == "run_payload_cap"
    assert second.truncated is True


# --------------------------------------------------------------- refusal rows


async def test_a_repeated_refusal_is_recorded_once():
    kwargs: dict[str, Any] = {
        "chat_id": -100900,
        "user_id": 9001,
        "message_id": 5,
        "reason": "quota",
    }
    await trace.note_rejection("chat", **kwargs)
    await trace.note_rejection("chat", **kwargs)

    rows = await wait_for_runs(1)
    await asyncio.sleep(0.05)
    rows = await runs()
    assert len(rows) == 1
    run = rows[0]
    assert (run.status, run.reject_reason) == ("rejected", "quota")
    assert (run.kind, run.event_count) == ("chat", 0)
    assert (run.requests, run.input_tokens, run.output_tokens) == (0, 0, 0)


# ------------------------------------------------------------ message replay


def _request_draft(
    kind: str, events: list[dao.AgentRunEventDraft]
) -> dao.AgentRunDraft:
    now = datetime.now(UTC)
    return dao.AgentRunDraft(
        kind=kind,
        status="ok",
        started_at=now,
        finished_at=now,
        duration_ms=0,
        events=tuple(events),
        output_kind="str",
        output_text="ok",
    )


async def test_request_messages_replay_from_prefix_increments():
    first = [
        {"parts": [{"content": "one", "part_kind": "user-prompt"}], "kind": "request"}
    ]
    second = [
        *first,
        {"parts": [{"content": "two", "part_kind": "user-prompt"}], "kind": "request"},
    ]
    await dao.record_trace(
        [
            _request_draft(
                "chat",
                [
                    dao.AgentRunEventDraft(
                        seq=1,
                        kind="model_request",
                        payload={
                            "messages_total": len(first),
                            "messages_prefix_len": 0,
                            "messages": first,
                        },
                    ),
                    dao.AgentRunEventDraft(
                        seq=2,
                        kind="model_request",
                        payload={
                            "messages_total": len(second),
                            "messages_prefix_len": 1,
                            "messages": second[1:],
                        },
                    ),
                ],
            )
        ]
    )
    run = (await runs())[0]
    assert await dao.reconstruct_request_messages(run.id, 1) == first
    assert await dao.reconstruct_request_messages(run.id, 2) == second
    # A step that is not a request has nothing to replay.
    assert await dao.reconstruct_request_messages(run.id, 3) is None


async def test_a_capped_request_cannot_be_replayed():
    payload = {
        "truncated": True,
        "reason": "event_payload_cap",
        "chars": 5_000_000,
    }
    await dao.record_trace(
        [
            _request_draft(
                "chat",
                [
                    dao.AgentRunEventDraft(
                        seq=1, kind="model_request", payload=payload, truncated=True
                    )
                ],
            )
        ]
    )
    run = (await runs())[0]
    assert await dao.reconstruct_request_messages(run.id, 1) is None


# ------------------------------------------------------------- real agent run


def _two_tool_rounds(seen: list[list[Any]]):
    """A model that calls a tool twice, then answers - three requests, one run."""

    def respond(messages: list[Any], _info: Any) -> ModelResponse:
        seen.append(list(messages))
        round_number = len(seen)
        if round_number <= 2:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="echo",
                        args={"text": f"t{round_number}"},
                        tool_call_id=f"c{round_number}",
                    )
                ]
            )
        return ModelResponse(parts=[TextPart(content="finished")])

    return respond


def echo(text: str) -> str:
    """Echo the text back."""
    return f"echo:{text}"


def boom() -> str:
    """Always fails, to put a tool error on the record."""
    raise RuntimeError("boom")


_HISTORY_MARK = "the rewritten history"


def _mark_user_prompts(message: Any) -> Any:
    """Prefix every unmarked user prompt in one message, preserving its shape.

    Idempotent on purpose: a rewritten message can come back as history, and marking
    it twice would rewrite the same conversation differently on every request.
    """
    if not isinstance(message, ModelRequest):
        return message
    marked = f"{_HISTORY_MARK}: "
    parts = [
        dataclasses.replace(part, content=f"{marked}{part.content}")
        if getattr(part, "part_kind", "") == "user-prompt"
        and isinstance(part.content, str)
        and not part.content.startswith(marked)
        else part
        for part in message.parts
    ]
    return dataclasses.replace(message, parts=parts)


class _RewritesHistory(AbstractCapability[Any]):
    """Stands in for `ProcessHistory`: rewrites the messages before the model runs.

    The trace has to sit inside this capability for a recorded request to be the
    request the model was given, so this marks every user prompt: the mark can only
    reach the database through a trace that saw the rewritten list.
    """

    async def before_model_request(
        self, ctx: RunContext[Any], request_context: ModelRequestContext
    ) -> ModelRequestContext:
        request_context.messages = [
            _mark_user_prompts(message) for message in request_context.messages
        ]
        return request_context


def test_the_capability_sits_innermost():
    """The ordering is what makes `model_request` the model's request, not the raw one."""
    ordering = trace.AgentTraceCapability().get_ordering()
    assert ordering is not None
    assert ordering.position == "innermost"


async def test_a_real_run_records_requests_responses_and_tool_results():
    """The capability, the buffer and the database, driven by a real agent run."""
    seen: list[list[Any]] = []
    provider = Agent(
        model=FunctionModel(_two_tool_rounds(seen)),
        tools=[echo],
        instructions="be brief",
        capabilities=[_RewritesHistory(), trace.AgentTraceCapability()],
    )

    session = await trace.start_trace("chat", chat_id=-100, user_id=7, message_id=42)
    assert session is not None
    result = await provider.run("hello")
    task = trace.finish_trace(session, usage=result.usage, output=result.output)
    assert task is not None
    await task

    run = (await runs())[0]
    assert run.status == "ok"
    assert run.output_text == "finished"
    assert run.requests == 3 and run.tool_calls == 2

    events = await stored_events(run.id)
    kinds = [event.kind for event in events]
    assert kinds.count("model_request") == 3
    assert kinds.count("model_response") == 3
    assert kinds.count("tool_call") == 2
    assert kinds.count("tool_result") == 2

    requests = [event for event in events if event.kind == "model_request"]
    first_request = requests[0]
    assert isinstance(first_request.payload, dict)
    # No caller supplied a model name, so it comes from the first response event.
    assert run.model_name == first_request.payload["model"]
    assert len(seen) == 3
    for index, event in enumerate(requests):
        replay = await dao.reconstruct_request_messages(run.id, event.seq)
        # The stored transcript is the one the model was handed - including the
        # history rewrite a capability outside the trace applied.
        assert replay == trace._serialize_messages(seen[index])
        # Anchored on content this test controls, so a serializer that silently drops
        # parts fails here rather than agreeing with itself. Request n carries the
        # tool round the model answered after request n-1, and the last one its reply.
        stored = json.dumps(replay, ensure_ascii=False)
        assert _HISTORY_MARK in stored, "the stored request must be the rewritten one"
        if index:
            assert f"echo:t{index}" in stored, "the tool return must be stored"
            assert f'"text": "t{index}"' in stored, "the tool arguments must be stored"
        payload = event.payload
        assert isinstance(payload, dict)
        # Every event stores a slice plus the full length, never the whole thing.
        assert (
            payload["messages_prefix_len"] + len(payload["messages"])
            == payload["messages_total"]
        )
        if index:
            # A later request must reuse its predecessor's prefix, otherwise the
            # turn stores one full copy of the history per request.
            assert payload["messages_prefix_len"] > 0
            assert len(payload["messages"]) < payload["messages_total"]

    # The reply itself lives in the response events, not in a later request.
    responses = [event.payload for event in events if event.kind == "model_response"]
    assert any(
        "finished" in json.dumps(payload, ensure_ascii=False)
        for payload in responses
        if isinstance(payload, dict)
    ), "the assistant text must be stored"

    tool_results = [event for event in events if event.kind == "tool_result"]
    assert [
        event.payload["result"]
        for event in tool_results
        if isinstance(event.payload, dict)
    ] == ["echo:t1", "echo:t2"]
    assert all(event.duration_ms is not None for event in tool_results)

    instruction_text = str(first_request.payload["instruction_parts"])
    assert "be brief" in instruction_text
    assert first_request.payload["messages_total"] == 1
    assert first_request.payload["messages_prefix_len"] == 0


async def test_a_failing_model_call_is_recorded_as_an_event_and_a_status():
    def explode(_messages: list[Any], _info: Any) -> ModelResponse:
        raise RuntimeError("provider exploded")

    provider = Agent(
        model=FunctionModel(explode),
        capabilities=[trace.AgentTraceCapability()],
    )
    session = await trace.start_trace("chat", chat_id=-100, user_id=7)
    assert session is not None
    with pytest.raises(Exception):
        await provider.run("hello")
    task = trace.finish_trace(session, status="error", error=RuntimeError("exploded"))
    assert task is not None
    await task

    run = (await runs())[0]
    assert run.status == "error"
    assert run.error_class == "RuntimeError"

    events = await stored_events(run.id)
    errors = [event for event in events if event.kind == "error"]
    assert errors and errors[0].status == "error"
    assert isinstance(errors[0].payload, dict)
    assert errors[0].payload["phase"] == "model_request"


# --------------------------------------------------------------- runner wiring


class _RefusalMessage:
    """The minimum `run_agent`'s refusal path touches."""

    id = 77
    chat = SimpleNamespace(id=-100901, type=pyrogram.enums.ChatType.SUPERGROUP)

    def __init__(self) -> None:
        self.replies: list[str] = []

    async def reply_text(self, text: str, **_kwargs: object) -> None:
        self.replies.append(text)


async def test_run_agent_records_a_quota_refusal(monkeypatch):
    async def never(*_args: object, **_kwargs: object) -> bool:
        return False

    monkeypatch.setattr(quota, "can_start", never)
    monkeypatch.setattr(app_config, "agent_run_timeout", 0, raising=False)

    message = _RefusalMessage()
    subject = quota.Subject(user_id=9101, chat_id=-100901, in_group=True)
    await runner.run_agent(  # type: ignore[arg-type]
        agi=object(),  # type: ignore[arg-type]
        client=SimpleNamespace(),  # type: ignore[arg-type]
        message=message,  # type: ignore[arg-type]
        user_id=9101,
        chat_id=-100901,
        user_prompt=[],
        history=[],
        deps=SimpleNamespace(),  # type: ignore[arg-type]
        multimodal_model=None,
        model=None,
        lang="zh-CN",
        subject=subject,
        trace_kind="chat",
    )

    rows = await wait_for_runs(1)
    run = rows[0]
    assert (run.kind, run.status, run.reject_reason) == ("chat", "rejected", "quota")
    assert (run.chat_id, run.user_id, run.message_id) == (-100901, 9101, 77)
    assert run.event_count == 0
    assert message.replies  # the user was told why


async def test_the_run_record_context_is_cleared_after_the_run():
    """A finished run must not leave itself installed for the next call."""
    session = await trace.start_trace("chat")
    assert session is not None
    task = trace.finish_trace(session, output="ok")
    assert task is not None
    await task
    assert trace.current_session() is None


async def test_a_disabled_trace_starts_no_session(monkeypatch):
    monkeypatch.setattr(app_config, "agent_trace_enabled", False, raising=False)
    session = await trace.start_trace("chat", chat_id=-1)
    assert session is None
    # Every marker is a no-op, so callers need no guard of their own.
    trace.mark_trace(session, output="ignored")
    assert trace.finish_trace(session) is None


# --------------------------------------------------------------- retention


async def test_cleanup_removes_only_old_runs_and_their_events():
    old = datetime.now(UTC) - timedelta(days=40)
    recent = datetime.now(UTC)
    await dao.record_trace(
        [
            dao.AgentRunDraft(
                kind="chat",
                status="ok",
                started_at=old,
                finished_at=old,
                duration_ms=0,
                events=(
                    dao.AgentRunEventDraft(
                        seq=1, kind="steering", payload={"texts": []}
                    ),
                ),
            ),
            dao.AgentRunDraft(
                kind="chat",
                status="ok",
                started_at=recent,
                finished_at=recent,
                duration_ms=0,
                events=(
                    dao.AgentRunEventDraft(
                        seq=1, kind="steering", payload={"texts": []}
                    ),
                ),
            ),
        ]
    )
    rows = await runs()
    assert len(rows) == 2

    removed = await dao.delete_runs_before(datetime.now(UTC) - timedelta(days=30))
    assert removed == 1
    remaining = await runs()
    assert [row.started_at.replace(tzinfo=None) for row in remaining] == [
        recent.replace(tzinfo=None)
    ]
    assert len(await stored_events(rows[1].id)) == 1
    assert await stored_events(rows[0].id) == [], "its events must not be orphaned"
    assert await dao.get_run(rows[0].id) is None


async def test_paging_filters_and_search():
    now = datetime.now(UTC)
    drafts = [
        dao.AgentRunDraft(
            kind="chat",
            status="ok",
            started_at=now - timedelta(minutes=index),
            finished_at=now,
            duration_ms=0,
            chat_id=-100 + index,
            user_id=5,
            output_text="alpha" if index == 0 else "beta",
        )
        for index in range(3)
    ]
    await dao.record_trace(drafts)

    page = await dao.get_runs_page(1, 2)
    assert page.total == 3 and len(page.items) == 2
    # Newest first.
    assert page.items[0].started_at > page.items[1].started_at

    assert (await dao.get_runs_page(1, 10, chat_id=-100)).total == 1
    assert (await dao.get_runs_page(1, 10, user_id=5)).total == 3
    assert (await dao.get_runs_page(1, 10, kind="chat")).total == 3
    assert (await dao.get_runs_page(1, 10, kind="ask")).total == 0
    assert (await dao.get_runs_page(1, 10, status="ok")).total == 3
    assert (await dao.get_runs_page(1, 10, status="error")).total == 0
    assert (await dao.get_runs_page(1, 10, query="alpha")).total == 1
    assert (await dao.get_runs_page(1, 10, since=now + timedelta(seconds=1))).total == 0
    assert (
        await dao.get_runs_page(1, 10, until=now - timedelta(minutes=10))
    ).total == 0


class _TurnMessage:
    """The parts of a Telegram message `run_agent` and its body read."""

    id = 909
    chat = SimpleNamespace(id=-100902, type=pyrogram.enums.ChatType.SUPERGROUP)

    def __init__(self) -> None:
        self.replies: list[str] = []

    async def reply_text(self, text: str, **_kwargs: object) -> None:
        self.replies.append(text)


class _TypingClient:
    async def send_chat_action(self, *_args: object, **_kwargs: object) -> bool:
        return True


async def test_a_whole_runner_turn_records_the_run_the_ledger_was_billed_for(
    monkeypatch,
):
    """The wiring, end to end: gates -> agent run -> settle -> the recorded trace.

    The trace and the token ledger must agree because both read the same run
    usage; a run whose row disagreed with what was charged would make the panel
    worse than useless.
    """
    monkeypatch.setattr(app_config, "agent_streaming", False, raising=False)
    monkeypatch.setattr(app_config, "agent_run_timeout", 0, raising=False)
    monkeypatch.setattr(
        app_config, "agent_quota_free_daily_tokens", 1_000_000, raising=False
    )
    monkeypatch.setattr(runner, "check_needs_multimodal", lambda *_a, **_k: False)
    monkeypatch.setattr(runner, "log_run_cache_stats", lambda *_a, **_k: None)

    async def fake_reply(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(runner, "reply_output", fake_reply)

    seen: list[list[Any]] = []
    model = FunctionModel(_two_tool_rounds(seen))
    monkeypatch.setattr(runner.provider, "make_chat_model", lambda *_a, **_k: model)
    monkeypatch.setattr(runner.provider, "make_model_settings", lambda *_a, **_k: None)

    provider = Agent(
        model=model,
        tools=[echo],
        instructions="be brief",
        capabilities=[trace.AgentTraceCapability()],
    )
    message = _TurnMessage()
    subject = quota.Subject(user_id=9201, chat_id=-100902, in_group=True)

    # The turn writes the conversation cache, which is process-wide; other tests
    # count its keys, so this test does not leave any behind.
    await memttlcache.delete(state.history_key(-100902, 9201))
    await runner.run_agent(  # type: ignore[arg-type]
        agi=provider,
        client=_TypingClient(),  # type: ignore[arg-type]
        message=message,  # type: ignore[arg-type]
        user_id=9201,
        chat_id=-100902,
        user_prompt=["hello"],
        history=[],
        deps=SimpleNamespace(history=[], user_id=9201, chat_id=-100902),  # type: ignore[arg-type]
        multimodal_model=None,
        model=model,
        lang="zh-CN",
        subject=subject,
        trace_kind="chat",
    )

    run = (await wait_for_runs(1))[0]
    assert run.status == "ok"
    assert run.kind == "chat"
    assert (run.requests, run.tool_calls) == (3, 2)
    assert run.output_text == "finished"
    # And it is filed under the conversation it belongs to.
    assert run.session_id == await trace.conversation_session(-100902, 9201)

    _, _, input_tokens, output_tokens = await database.get_usage(
        database.SCOPE_USER, 9201, database.utc_day()
    )
    assert (input_tokens, output_tokens) == (run.input_tokens, run.output_tokens)
    assert run.input_tokens > 0

    # Every request of the turn is on record, and the last one replays completely.
    events = await stored_events(run.id)
    requests = [event for event in events if event.kind == "model_request"]
    assert len(requests) == 3
    last_request = requests[-1]
    assert isinstance(last_request.payload, dict)
    replay = await dao.reconstruct_request_messages(run.id, last_request.seq)
    assert len(seen) == 3
    assert replay == trace._serialize_messages(seen[-1])

    await memttlcache.delete(state.history_key(-100902, 9201))
    await memttlcache.delete(state.prompt_coverage_key(-100902, 9201))


async def test_the_daily_cleanup_honours_the_retention_window(monkeypatch):
    """The job's own switch: 0 means keep everything, a window means delete."""
    from kmua.bot import jobs

    old = datetime.now(UTC) - timedelta(days=40)
    recent = datetime.now(UTC)

    def draft(started: datetime) -> dao.AgentRunDraft:
        return dao.AgentRunDraft(
            kind="chat",
            status="ok",
            started_at=started,
            finished_at=started,
            duration_ms=0,
            events=(
                dao.AgentRunEventDraft(seq=1, kind="steering", payload={"texts": []}),
            ),
        )

    await dao.record_trace([draft(old), draft(recent)])

    monkeypatch.setattr(app_config, "agent_trace_retention_days", 0, raising=False)
    await jobs._cleanup_agent_traces()
    assert len(await runs()) == 2, "a non-positive window keeps every run"

    monkeypatch.setattr(app_config, "agent_trace_retention_days", 30, raising=False)
    await jobs._cleanup_agent_traces()
    remaining = await runs()
    assert len(remaining) == 1
    assert remaining[0].started_at.replace(tzinfo=None) == recent.replace(tzinfo=None)
    assert await stored_events(remaining[0].id)
    async with AsyncSessionFactory() as session:
        rows = await session.scalars(sqlalchemy.select(AgentRunEvent))
    assert len(list(rows)) == 1, "the expired run's events must be deleted too"


async def test_run_agent_records_a_whitelist_refusal(monkeypatch):
    """The other documented refusal reason reaches the row it belongs to."""
    monkeypatch.setattr(runner, "is_chat_allowed", lambda _chat_id: False)

    message = _RefusalMessage()
    await runner.run_agent(  # type: ignore[arg-type]
        agi=object(),  # type: ignore[arg-type]
        client=SimpleNamespace(),  # type: ignore[arg-type]
        message=message,  # type: ignore[arg-type]
        user_id=9202,
        chat_id=-100902,
        user_prompt=[],
        history=[],
        deps=SimpleNamespace(),  # type: ignore[arg-type]
        multimodal_model=None,
        model=None,
        lang="zh-CN",
        subject=quota.Subject(user_id=9202, chat_id=-100902, in_group=True),
        trace_kind="chat",
    )

    run = (await wait_for_runs(1))[0]
    assert (run.status, run.reject_reason) == ("rejected", "whitelist")
    assert message.replies == [], "a whitelisted-out chat is refused silently"


async def test_run_agent_records_a_cancelled_turn(monkeypatch):
    """Cancellation is a run outcome too: the row must say so, not 'incomplete'."""
    monkeypatch.setattr(app_config, "agent_run_timeout", 0, raising=False)

    entered = asyncio.Event()

    async def stalled(**_kwargs: object) -> None:
        entered.set()
        await asyncio.sleep(30)

    monkeypatch.setattr(runner, "_run_agent_impl", stalled)

    message = _RefusalMessage()
    task = asyncio.create_task(
        runner.run_agent(  # type: ignore[arg-type]
            agi=object(),  # type: ignore[arg-type]
            client=SimpleNamespace(),  # type: ignore[arg-type]
            message=message,  # type: ignore[arg-type]
            user_id=9203,
            chat_id=-100902,
            user_prompt=[],
            history=[],
            deps=SimpleNamespace(),  # type: ignore[arg-type]
            multimodal_model=None,
            model=None,
            lang="zh-CN",
            subject=quota.Subject(user_id=9203, chat_id=-100902, in_group=True),
            trace_kind="chat",
        )
    )
    # Cancel inside the run, not while the gate is still in flight.
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    run = (await wait_for_runs(1))[0]
    assert run.status == "cancelled"
    assert run.error_class is None
    assert run.output_kind is None


# ------------------------------------------------------------------ sessions


async def write_run(kind: str, *, chat_id: int, user_id: int) -> str | None:
    """One whole run of that conversation, then its id - the way a caller does it."""
    session = await trace.start_trace(kind, chat_id=chat_id, user_id=user_id)
    assert session is not None
    task = trace.finish_trace(session, output="x")
    assert task is not None
    await task
    return session.session_id


async def test_runs_of_one_conversation_share_a_session_id():
    first = await write_run("chat", chat_id=-100, user_id=7)
    second = await write_run("chat", chat_id=-100, user_id=7)
    assert first is not None
    assert first == second

    # Another participant, or another chat, is another conversation.
    other_user = await write_run("chat", chat_id=-100, user_id=8)
    other_chat = await write_run("chat", chat_id=-200, user_id=7)
    assert other_user != first
    assert other_chat != first

    by_session = {row.session_id for row in await runs()}
    assert None not in by_session
    assert len(by_session) == 3


async def test_a_nested_run_inherits_its_parent_session():
    parent = await trace.start_trace("chat", chat_id=-100, user_id=7)
    child = await trace.start_trace("compaction")
    assert parent is not None and child is not None
    assert child.session_id == parent.session_id
    child.note_steering(["child event"])
    assert parent.events == [], "a child event must not land on the parent"
    trace.finish_trace(child, output="summary")
    task = trace.finish_trace(parent, output="answer")
    assert task is not None
    await task

    rows = {row.kind: row for row in await runs()}
    assert rows["compaction"].session_id == rows["chat"].session_id
    assert rows["compaction"].parent_run_id == rows["chat"].id
    # Each run stores its own steps, and only its own.
    child_events = await stored_events(rows["compaction"].id)
    assert [(event.kind, event.payload) for event in child_events] == [
        ("steering", {"texts": ["child event"]})
    ]
    assert [event.kind for event in await stored_events(rows["chat"].id)] == []


async def test_a_run_without_a_conversation_has_no_session():
    """RSS work and sticker descriptions belong to no thread, so they group with none."""
    session = await trace.start_trace("rss_digest")
    assert session is not None
    assert session.session_id is None
    task = trace.finish_trace(session, output="digest")
    assert task is not None
    await task

    assert (await runs())[0].session_id is None


def test_a_session_id_is_a_time_ordered_uuidv7():
    from time import time

    from kmua.plugins.agent import state as agent_state

    first = agent_state.new_session_id()
    second = agent_state.new_session_id()

    assert len(first) == 32 and len(second) == 32
    assert first != second
    # Version 7 with the RFC variant, stamped by the current clock: an id whose
    # fields were assembled wrong fails all three.
    parsed = uuid.UUID(hex=first)
    assert parsed.version == 7
    assert parsed.variant == uuid.RFC_4122
    assert abs((parsed.int >> 80) - int(time() * 1000)) < 60_000
    # What version 7 buys over a random id: they sort by when they were minted, and
    # a batch keeps that property across the millisecond boundary.
    ids = [agent_state.new_session_id() for _ in range(1000)]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)


async def test_forget_opens_a_new_session():
    """/forget clears the conversation, so the next run of it is a new instance."""
    from kmua.plugins.agent import agent as agent_plugin
    from kmua.plugins.agent import state as agent_state

    opened = await agent_state.conversation_session(-100, 7)
    assert await agent_state.conversation_session(-100, 7) == opened, (
        "stable while it lasts"
    )

    await agent_plugin._clear_conversation_session(-100, 7)

    after = await agent_state.conversation_session(-100, 7)
    assert after != opened
    assert len(after) == 32


async def test_the_global_wipe_rotates_every_session():
    """What /clear_sessions does: every thread starts over, ids included."""
    from kmua.plugins.agent import agent as agent_plugin
    from kmua.plugins.agent import state as agent_state

    opened = {
        (chat, user): await agent_state.conversation_session(chat, user)
        for chat, user in ((-100, 7), (-100, 8), (-200, 7))
    }

    cleared = agent_plugin._clear_memstore_prefix(agent_state.SESSION_KEY_PREFIX)
    assert cleared == len(opened)

    for (chat, user), before_id in opened.items():
        assert await agent_state.conversation_session(chat, user) != before_id


def test_a_data_uri_part_is_reduced_to_metadata():
    """A URL part can carry a body inline; only the type and size may be stored."""
    from kmua.plugins.agent.trace import _serialize_messages

    body = base64.b64encode(b"\x89PNG-binary-body").decode()
    messages = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="view",
                    args={"image_url": f"data:image/png;base64,{body}"},
                    tool_call_id="c1",
                )
            ]
        ),
        ModelRequest(
            parts=[
                UserPromptPart(content=[ImageUrl(url=f"data:image/png;base64,{body}")])
            ]
        ),
    ]

    stored = json.dumps(_serialize_messages(messages), ensure_ascii=False)
    assert body not in stored, "the inline body must not be stored"
    assert "data:image/png" in stored, "the media type must survive"
    assert "omitted" in stored


def test_a_backwards_clock_does_not_mint_a_lower_id(monkeypatch):
    """Ids stay ordered even if the wall clock steps back (NTP, suspend, an operator)."""
    from kmua.plugins.agent import state as agent_state

    ticks = iter([1_800_000_000_000, 1_800_000_000_000, 1_799_999_999_000])

    monkeypatch.setattr(agent_state, "time_ns", lambda: next(ticks) * 1_000_000)
    ids = [agent_state.new_session_id() for _ in range(3)]

    assert ids == sorted(ids)
    assert [uuid.UUID(hex=value).int >> 80 for value in ids] == [
        1_800_000_000_000,
        1_800_000_000_000,
        1_800_000_000_000,
    ]


async def test_a_refusal_carries_the_conversation_session():
    await trace.note_rejection(
        "chat", chat_id=-555, user_id=7, message_id=1, reason="quota"
    )
    rows = await wait_for_runs(1)
    assert rows[0].session_id is not None
    assert rows[0].session_id == await trace.conversation_session(-555, 7)


async def test_a_failing_tool_call_is_recorded_with_its_error(monkeypatch):
    """A tool that raises is a step of the run too, and its cost is measurable."""
    seen: list[list[Any]] = []

    def respond(messages: list[Any], _info: Any) -> ModelResponse:
        seen.append(list(messages))
        if len(seen) == 1:
            return ModelResponse(
                parts=[ToolCallPart(tool_name="boom", args={}, tool_call_id="c1")]
            )
        return ModelResponse(parts=[TextPart(content="I could not do that")])

    provider = Agent(
        model=FunctionModel(respond),
        tools=[boom],
        capabilities=[trace.AgentTraceCapability()],
    )

    session = await trace.start_trace("chat", chat_id=-100, user_id=7)
    assert session is not None
    with pytest.raises(RuntimeError):
        await provider.run("try it")
    task = trace.finish_trace(session, status="error", error=RuntimeError("boom"))
    assert task is not None
    await task

    run = (await runs())[0]
    assert run.status == "error"
    events = await stored_events(run.id)
    errors = [event for event in events if event.kind == "tool_result"]
    assert len(errors) == 1
    failed = errors[0]
    assert (failed.status, failed.name) == ("error", "boom")
    assert failed.duration_ms is not None
    assert isinstance(failed.payload, dict)
    assert failed.payload["error_class"] == "RuntimeError"
    assert "boom" in str(failed.payload["message"])


async def test_a_tool_returning_binary_metadata_stores_no_body():
    """A tool's own return value is a message part, so the body rule covers it."""
    seen: list[list[Any]] = []
    body = b"\x89PNG" + b"\x00" * 64

    def snapshot() -> bytes:
        """Return a raw binary payload."""
        return body

    def respond(messages: list[Any], _info: Any) -> ModelResponse:
        seen.append(list(messages))
        if len(seen) == 1:
            return ModelResponse(
                parts=[ToolCallPart(tool_name="snapshot", args={}, tool_call_id="c1")]
            )
        return ModelResponse(parts=[TextPart(content="got it")])

    provider = Agent(
        model=FunctionModel(respond),
        tools=[snapshot],
        capabilities=[trace.AgentTraceCapability()],
    )

    session = await trace.start_trace("chat", chat_id=-100, user_id=7)
    assert session is not None
    result = await provider.run("grab a snapshot")
    task = trace.finish_trace(session, usage=result.usage, output=result.output)
    assert task is not None
    await task

    run = (await runs())[0]
    events = await stored_events(run.id)
    stored = json.dumps([event.payload for event in events], ensure_ascii=False)
    assert '"kind": "binary"' in stored, "the return must be reduced to metadata"
    assert base64.b64encode(body).decode() not in stored, "no base64 body"
    assert "\\u0089PNG" not in stored, "no escaped body"
    # The same reduction applies to the messages the model was given.
    request = next(event for event in events if event.kind == "model_request")
    assert isinstance(request.payload, dict)
    assert request.payload["messages"], "the tool round must be in the increment"
    assert base64.b64encode(body).decode() not in json.dumps(request.payload)
