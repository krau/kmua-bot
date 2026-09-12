"""Recording agent runs: what each turn sent, what came back, and how it ended.

The capture side of the run trace. A `TraceSession` buffers one run's steps in
memory; `AgentTraceCapability` is the innermost capability of an agent, so it
observes the messages the model version of the request actually carries (after
`ProcessHistory` rewrote them) and the raw tool returns before any guardrail,
spill or clamp rewrote them. `finish_trace` hands the buffered session to
`kmua.database.agent_trace` in the background - never on the user's path, and a
failed write is a warning, not a failed run.

Three things are deliberately not recorded: binary content bodies (only their
media type, size and identifier survive), provider HTTP traffic (a streamed run
records the assembled response, not its deltas), and a run that crashed before it
finished (the row is written once, at the end).

A request's `messages` are stored as an increment: only the part past the longest
common prefix with the previous request of the same run. Reading them back means
replaying the run in order, which `reconstruct_request_messages` does.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import time
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability, CapabilityOrdering
from pydantic_ai.messages import (
    BinaryContent,
    ModelMessagesTypeAdapter,
    ModelResponse,
    ToolCallPart,
)
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.tools import ToolDefinition

from kmua.common.memory_store import memttlcache
from kmua.common.utils import spawn
from kmua.config import app_config
from kmua.database.agent_trace import (
    AgentRunDraft,
    AgentRunEventDraft,
    record_rejection,
    record_trace,
)
from kmua.logger import logger

# Per-run ceilings, not configuration: they exist so one pathological run cannot
# fill the database, and a deployment that hits them has a bug worth seeing.
_MAX_EVENTS_PER_RUN = 200
_MAX_EVENT_PAYLOAD_CHARS = 2_000_000
_MAX_RUN_PAYLOAD_CHARS = 10_000_000
_MAX_ERROR_CHARS = 2_000

# How long one refusal silences the next identical one. The entry gate and the
# runner's own gate both evaluate the same account, and an exhausted user keeps
# triggering both; this collapses that into one row.
_REJECT_TTL_SECONDS = 60

_BINARY_KIND = "binary"
_OUTPUT_KINDS = {"EndTurn": "end_turn", "AskUserOutput": "ask_user"}

_UNSET: Any = object()


def safe_value(value: Any) -> Any:
    """Render a value as JSON without carrying binary payloads.

    Binary content becomes its metadata (media type, byte count, identifier);
    dataclasses become field maps; anything else unserializable becomes its type
    name. Callers' only obligation is to keep it that way.
    """
    if isinstance(value, BinaryContent):
        marker: dict[str, Any] = {
            "kind": "binary",
            "media_type": str(value.media_type),
            "size": len(value.data),
        }
        identifier = getattr(value, "identifier", None)
        if identifier:
            marker["identifier"] = identifier
        return marker
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"kind": "binary", "size": len(value)}
    if isinstance(value, dict):
        return {str(key): safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [safe_value(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: safe_value(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    return f"<{type(value).__name__}>"


def output_kind_of(output: Any) -> str:
    """Classify a run's final output for the run row."""
    if isinstance(output, str):
        return "str"
    if output is None:
        return "none"
    return _OUTPUT_KINDS.get(type(output).__name__, "none")


def _redact_string(text: str) -> str:
    """Rewrite credentials out of text, when masking is on."""
    if not app_config.agent_secret_masking:
        return text
    # Deferred: the detectors module is only needed here, and importing it at
    # module scope would tie this module to the guardrail stack.
    from pydantic_ai_harness.guardrails.detectors import redact_secrets

    result = redact_secrets(text)
    replacement = result.replacement
    if result.action == "replace" and isinstance(replacement, str):
        return replacement
    return text


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _truncate(value: Any, limit: int) -> tuple[Any, bool]:
    """Cut over-long strings, leaving the surrounding structure alone."""
    if isinstance(value, str):
        if limit > 0 and len(value) > limit:
            return value[:limit], True
        return value, False
    if isinstance(value, dict):
        cut = False
        out: dict[str, Any] = {}
        for key, item in value.items():
            out[key], trimmed = _truncate(item, limit)
            cut = cut or trimmed
        return out, cut
    if isinstance(value, list):
        cut = False
        out_list: list[Any] = []
        for item in value:
            item_out, trimmed = _truncate(item, limit)
            out_list.append(item_out)
            cut = cut or trimmed
        return out_list, cut
    return value, False


def _json_chars(payload: Any) -> int:
    try:
        return len(json.dumps(payload, ensure_ascii=False))
    except (TypeError, ValueError):
        return len(str(payload))


def _binary_marker(value: dict[str, Any]) -> dict[str, Any]:
    """Metadata for one serialized binary content value, without its body."""
    data = value.get("data")
    if isinstance(data, (bytes, bytearray, memoryview)):
        size = len(data)
    elif isinstance(data, str):
        size = len(data)
    else:
        size = 0
    marker: dict[str, Any] = {
        "kind": _BINARY_KIND,
        "media_type": value.get("media_type"),
        "size": size,
    }
    if value.get("identifier"):
        marker["identifier"] = value["identifier"]
    return marker


def _json_safe_message(value: Any) -> Any:
    """Reduce one dumped message value to something JSON can hold safely.

    The message dump is walked in python mode, which hands back raw `bytes`
    (inside a tool's own return value as much as inside a media part) and
    `datetime` objects, so this is where both are normalised: bytes and binary
    content become metadata and nothing else, and timestamps become ISO strings.
    A single implementation, because a binary body that slips through here lands
    in the database.
    """
    if isinstance(value, dict):
        if value.get("kind") == _BINARY_KIND and "data" in value:
            return _binary_marker(value)
        return {str(key): _json_safe_message(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe_message(item) for item in value]
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"kind": _BINARY_KIND, "size": len(value)}
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return f"<{type(value).__name__}>"


def _serialize_messages(messages: Sequence[Any]) -> list[dict[str, Any]]:
    """Serialize messages to the shape the panel renders and replays.

    Python-mode dump followed by `_json_safe_message`: the pair is total over what
    pydantic-ai puts in a message, which is what keeps a binary body out of the
    database even when a tool returned one inside its own value.
    """
    docs = ModelMessagesTypeAdapter.dump_python(list(messages), mode="python")
    return [_json_safe_message(doc) for doc in docs]


def _common_prefix_len(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> int:
    length = min(len(left), len(right))
    index = 0
    while index < length and left[index] == right[index]:
        index += 1
    return index


def _model_name(request_context: ModelRequestContext) -> str:
    return (
        getattr(request_context.model, "model_name", None)
        or request_context.model_id
        or type(request_context.model).__name__
    )


def _error_summary(error: BaseException) -> str:
    return f"{error.__class__.__name__}: {error}"[:_MAX_ERROR_CHARS]


def _elapsed_ms(started: float | None) -> int | None:
    if started is None:
        return None
    return max(0, int((time.monotonic() - started) * 1000))


class _Event:
    """One buffered step; converted and capped when the run is written."""

    __slots__ = ("kind", "name", "status", "duration_ms", "payload")

    def __init__(
        self,
        kind: str,
        *,
        name: str | None = None,
        status: str = "ok",
        duration_ms: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.kind = kind
        self.name = name
        self.status = status
        self.duration_ms = duration_ms
        self.payload = payload


class TraceSession:
    """One run's buffer, plus everything known about how it ended."""

    def __init__(
        self,
        kind: str,
        *,
        chat_id: int | None = None,
        user_id: int | None = None,
        message_id: int | None = None,
        model_role: str | None = None,
        streaming: bool = False,
    ) -> None:
        self.kind = kind
        self.chat_id = chat_id
        self.user_id = user_id
        self.message_id = message_id
        self.model_role = model_role
        self.streaming = streaming

        self.events: list[_Event] = []
        self.dropped = 0
        self.children: list[TraceSession] = []
        self.parent: TraceSession | None = None

        self.status: str | None = None
        self.reject_reason: str | None = None
        self.error_class: str | None = None
        self.error_message: str | None = None
        self.output_text: str | None = None
        self.output_chars: int | None = None
        self.output_kind: str | None = None
        self.result_seen = False
        self.model_name: str | None = None
        self.requests = 0
        self.tool_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_read_tokens = 0
        self.cache_write_tokens = 0

        self.started_at = datetime.now(UTC)
        self.finished_at: datetime | None = None
        self.prev_request_messages: list[dict[str, Any]] | None = None
        self._request_started: float | None = None
        self._tool_started: dict[str, float] = {}
        self._token: Token[TraceSession | None] | None = None

    # ---------------------------------------------------------------- buffering

    def _append(
        self,
        kind: str,
        *,
        name: str | None = None,
        status: str = "ok",
        duration_ms: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if len(self.events) >= _MAX_EVENTS_PER_RUN:
            self.dropped += 1
            return
        self.events.append(
            _Event(
                kind,
                name=name,
                status=status,
                duration_ms=duration_ms,
                payload=payload,
            )
        )

    # ------------------------------------------------------------------- hooks

    def note_model_request(self, request_context: ModelRequestContext) -> None:
        docs = _serialize_messages(request_context.messages)
        previous = self.prev_request_messages
        prefix_len = 0 if previous is None else _common_prefix_len(previous, docs)
        self.prev_request_messages = docs
        self._request_started = time.monotonic()
        name = _model_name(request_context)
        self._append(
            "model_request",
            name=name,
            payload={
                "model": name,
                "model_id": request_context.model_id,
                "streaming": bool(request_context.streaming),
                "model_settings": safe_value(request_context.model_settings),
                "instruction_parts": safe_value(
                    getattr(
                        request_context.model_request_parameters,
                        "instruction_parts",
                        None,
                    )
                ),
                "messages_total": len(docs),
                "messages_prefix_len": prefix_len,
                "messages": docs[prefix_len:],
            },
        )

    def note_model_response(
        self, request_context: ModelRequestContext, response: ModelResponse
    ) -> None:
        duration_ms = _elapsed_ms(self._request_started)
        self._request_started = None
        name = _model_name(request_context)
        self._append(
            "model_response",
            name=name,
            duration_ms=duration_ms,
            payload={"model": name, "messages": _serialize_messages([response])},
        )

    def note_model_error(
        self, request_context: ModelRequestContext, error: Exception
    ) -> None:
        self._request_started = None
        self._append(
            "error",
            name=error.__class__.__name__,
            status="error",
            payload={
                "phase": "model_request",
                "message": _error_summary(error),
                "model": _model_name(request_context),
            },
        )

    def note_tool_call(self, call: ToolCallPart, args: Any) -> None:
        self._tool_started[call.tool_call_id] = time.monotonic()
        self._append(
            "tool_call",
            name=call.tool_name,
            payload={"tool_call_id": call.tool_call_id, "args": safe_value(args)},
        )

    def note_tool_result(self, call: ToolCallPart, result: Any) -> None:
        duration_ms = _elapsed_ms(self._tool_started.pop(call.tool_call_id, None))
        self._append(
            "tool_result",
            name=call.tool_name,
            duration_ms=duration_ms,
            payload={
                "tool_call_id": call.tool_call_id,
                "result": safe_value(result),
            },
        )

    def note_tool_error(self, call: ToolCallPart, error: Exception) -> None:
        duration_ms = _elapsed_ms(self._tool_started.pop(call.tool_call_id, None))
        self._append(
            "tool_result",
            name=call.tool_name,
            status="error",
            duration_ms=duration_ms,
            payload={
                "tool_call_id": call.tool_call_id,
                "error_class": error.__class__.__name__,
                "message": _error_summary(error),
            },
        )

    def note_steering(self, texts: Sequence[str]) -> None:
        self._append("steering", payload={"texts": list(texts)})


# The run whose model requests the hooks are currently observing. Nested runs
# (compaction inside a turn, transcription inside a turn) replace it for their own
# duration, so their events land in their own buffer rather than the parent's.
_current: ContextVar[TraceSession | None] = ContextVar("kmua_agent_trace", default=None)


def current_session() -> TraceSession | None:
    """The run being observed in this task, if any."""
    return _current.get()


def start_trace(
    kind: str,
    *,
    chat_id: int | None = None,
    user_id: int | None = None,
    message_id: int | None = None,
    model_role: str | None = None,
    streaming: bool = False,
) -> TraceSession | None:
    """Open a run buffer, nested in the enclosing one when there is one.

    Returns None when tracing is off, so every caller can treat the return value
    as "maybe a session" and the whole capture path disappears with the switch.
    """
    if not app_config.agent_trace_enabled:
        return None
    session = TraceSession(
        kind,
        chat_id=chat_id,
        user_id=user_id,
        message_id=message_id,
        model_role=model_role,
        streaming=streaming,
    )
    parent = _current.get()
    if parent is not None:
        parent.children.append(session)
        session.parent = parent
    session._token = _current.set(session)
    return session


def mark_trace(
    session: TraceSession | None,
    *,
    status: str | None = None,
    error: BaseException | None = None,
    reject_reason: str | None = None,
    usage: Any = None,
    output: Any = _UNSET,
    output_kind: str | None = None,
    model_name: str | None = None,
    model_role: str | None = None,
    streaming: bool | None = None,
) -> None:
    """Record how a run turned out, without writing anything yet.

    The first marker wins for `status`, so a later timeout cannot overwrite an
    error that already explained the run.
    """
    if session is None:
        return
    if status is not None and session.status is None:
        session.status = status
    if reject_reason is not None:
        session.reject_reason = reject_reason
    if error is not None:
        if session.status is None:
            session.status = "error"
        if session.error_class is None:
            session.error_class = error.__class__.__name__
            session.error_message = _error_summary(error)
    if usage is not None:
        session.requests = int(getattr(usage, "requests", 0) or 0)
        session.tool_calls = int(getattr(usage, "tool_calls", 0) or 0)
        session.input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        session.output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        session.cache_read_tokens = int(getattr(usage, "cache_read_tokens", 0) or 0)
        session.cache_write_tokens = int(getattr(usage, "cache_write_tokens", 0) or 0)
    if output is not _UNSET:
        session.result_seen = True
        session.output_kind = output_kind or output_kind_of(output)
        if isinstance(output, str):
            session.output_text = output
            session.output_chars = len(output)
        else:
            session.output_text = None
            session.output_chars = None
    if model_name is not None:
        session.model_name = model_name
    if model_role is not None:
        session.model_role = model_role
    if streaming is not None:
        session.streaming = streaming


def finish_trace(session: TraceSession | None, **markers: Any) -> asyncio.Task | None:
    """Close a run and, for a root run, schedule its write.

    Returns the flush task so tests (and only tests) can await it; production
    callers ignore it. A nested run is closed here too, but its write belongs to
    the root's flush, which is what keeps a turn and everything it spawned in one
    transaction.
    """
    if session is None:
        return None
    if session.finished_at is not None:
        return None
    mark_trace(session, **markers)
    session.finished_at = datetime.now(UTC)
    _resolve_status(session)
    if session._token is not None:
        try:
            _current.reset(session._token)
        except ValueError:
            # Set in a different context than the reset (a nested task); leaving
            # the value bound only affects that task's own lifetime.
            pass
        session._token = None
    if session.parent is not None:
        return None
    return spawn(_write_root(session), name="agent-trace-flush")


@asynccontextmanager
async def trace_scope(
    kind: str,
    *,
    chat_id: int | None = None,
    user_id: int | None = None,
    message_id: int | None = None,
    model_role: str | None = None,
    streaming: bool = False,
) -> AsyncIterator[TraceSession | None]:
    """Open and close a run around a block, without swallowing its exceptions.

    The body is expected to `mark_trace` its own result; an exception that escapes
    it is recorded and re-raised, so the block's error handling is untouched.
    """
    session = start_trace(
        kind,
        chat_id=chat_id,
        user_id=user_id,
        message_id=message_id,
        model_role=model_role,
        streaming=streaming,
    )
    try:
        yield session
    except asyncio.CancelledError:
        mark_trace(session, status="cancelled")
        raise
    except TimeoutError as e:
        mark_trace(session, status="timeout", error=e)
        raise
    except BaseException as e:
        mark_trace(session, status="error", error=e)
        raise
    finally:
        finish_trace(session)


def note_steering(texts: Sequence[str]) -> None:
    """Record queued user interjections delivered into the current run."""
    session = _current.get()
    if session is not None:
        session.note_steering(texts)


# ------------------------------------------------------------------ write path


def _resolve_status(session: TraceSession) -> None:
    if session.status is not None:
        return
    if session.result_seen:
        session.status = "ok"
        return
    session.status = "error"
    session.error_class = session.error_class or "AgentRunIncomplete"


def _prepare_payload(
    payload: dict[str, Any] | None, budget: list[int], limit: int
) -> tuple[dict[str, Any] | None, int | None, bool]:
    """Redact, cap and measure one event payload.

    `budget` is the run's remaining payload allowance, decremented in place: the
    per-event cap protects one giant step, the run cap protects a run made of many
    large ones.
    """
    if payload is None:
        return None, None, False
    chars = _json_chars(payload)
    if chars > _MAX_EVENT_PAYLOAD_CHARS or chars > budget[0]:
        reason = (
            "event_payload_cap"
            if chars > _MAX_EVENT_PAYLOAD_CHARS
            else "run_payload_cap"
        )
        return {"truncated": True, "reason": reason, "chars": chars}, chars, True
    budget[0] -= chars
    value, cut = _truncate(_redact(payload), limit)
    return value, chars, cut


def _first_response_model(events: Sequence[AgentRunEventDraft]) -> str | None:
    for event in events:
        if event.kind != "model_response" or not isinstance(event.payload, dict):
            continue
        model = event.payload.get("model")
        if isinstance(model, str) and model:
            return model
    return None


def _to_draft(session: TraceSession) -> AgentRunDraft:
    limit = app_config.agent_trace_max_field_chars
    budget = [_MAX_RUN_PAYLOAD_CHARS]
    events: list[AgentRunEventDraft] = []
    for seq, event in enumerate(session.events, start=1):
        payload, payload_chars, truncated = _prepare_payload(
            event.payload, budget, limit
        )
        events.append(
            AgentRunEventDraft(
                seq=seq,
                kind=event.kind,
                status=event.status,
                name=event.name,
                duration_ms=event.duration_ms,
                payload=payload,
                payload_chars=payload_chars,
                truncated=truncated,
            )
        )

    if session.status is None:
        session.status = "error"
        session.error_class = session.error_class or "AgentRunIncomplete"
    started = session.started_at
    finished = session.finished_at or started
    output_text = session.output_text
    if output_text is not None:
        output_text, _cut = _truncate(_redact_string(output_text), limit)
    error_message = session.error_message
    if error_message is not None:
        error_message = _redact_string(error_message)[:_MAX_ERROR_CHARS]

    return AgentRunDraft(
        kind=session.kind,
        status=session.status,
        reject_reason=session.reject_reason,
        chat_id=session.chat_id,
        user_id=session.user_id,
        message_id=session.message_id,
        model_name=session.model_name or _first_response_model(events),
        model_role=session.model_role,
        streaming=session.streaming,
        started_at=started,
        finished_at=finished,
        duration_ms=max(0, int((finished - started).total_seconds() * 1000)),
        events=tuple(events),
        children=tuple(_to_draft(child) for child in session.children),
        events_dropped=session.dropped,
        requests=session.requests,
        tool_calls=session.tool_calls,
        input_tokens=session.input_tokens,
        output_tokens=session.output_tokens,
        cache_read_tokens=session.cache_read_tokens,
        cache_write_tokens=session.cache_write_tokens,
        output_kind=session.output_kind,
        output_text=output_text,
        output_chars=session.output_chars,
        error_class=session.error_class,
        error_message=error_message,
    )


async def _write_root(session: TraceSession) -> None:
    kind = session.kind
    runs = 1 + len(session.children)
    try:
        if session.status == "rejected":
            await _write_rejection(
                kind=kind,
                chat_id=session.chat_id,
                user_id=session.user_id,
                message_id=session.message_id,
                reason=session.reject_reason or "quota",
                model_role=session.model_role,
                streaming=session.streaming,
            )
            return
        await record_trace([_to_draft(session)])
    except Exception as e:
        logger.warning(
            f"agent trace not recorded ({kind}, {runs} run(s)): "
            f"{e.__class__.__name__} - {e}"
        )


async def _write_rejection(
    *,
    kind: str,
    chat_id: int | None,
    user_id: int | None,
    message_id: int | None,
    reason: str,
    model_role: str | None,
    streaming: bool,
) -> None:
    key = f"agent_trace_reject:{kind}:{chat_id}:{user_id}:{reason}"
    if await memttlcache.get(key):
        return
    await memttlcache.set(key, True, ttl=_REJECT_TTL_SECONDS)
    now = datetime.now(UTC)
    draft = AgentRunDraft(
        kind=kind,
        status="rejected",
        reject_reason=reason,
        chat_id=chat_id,
        user_id=user_id,
        message_id=message_id,
        model_role=model_role,
        streaming=streaming,
        started_at=now,
        finished_at=now,
        duration_ms=0,
    )
    await record_rejection(draft)


async def note_rejection(
    kind: str,
    *,
    chat_id: int | None = None,
    user_id: int | None = None,
    message_id: int | None = None,
    reason: str,
    model_role: str | None = None,
    streaming: bool = False,
) -> None:
    """Record a run refused before it started, at most once per minute per identity.

    Only the quota and whitelist gates call this. Refusals that are not a decision
    about a run - a chat where `ai_reply` is off, a blocked user, a message that
    arrived mid-turn - are not runs and are not recorded.
    """
    if not app_config.agent_trace_enabled:
        return
    try:
        await _write_rejection(
            kind=kind,
            chat_id=chat_id,
            user_id=user_id,
            message_id=message_id,
            reason=reason,
            model_role=model_role,
            streaming=streaming,
        )
    except Exception as e:
        logger.warning(
            f"agent trace rejection not recorded ({kind}, {reason}): "
            f"{e.__class__.__name__} - {e}"
        )


# ------------------------------------------------------------------ capability


class AgentTraceCapability(AbstractCapability[Any]):
    """Feeds the current run's session from the agent lifecycle.

    Innermost on purpose: `before_model_request` then sees the messages the model
    is actually given (after history processing rewrote them), and the `after_*`
    hooks, which run inside-out, see tool returns before the outer guardrails and
    output limits replaced them.

    Holds no per-run state - every hook reads the session from the context - so one
    instance can be shared by any number of agents.
    """

    def get_ordering(self) -> CapabilityOrdering | None:
        return CapabilityOrdering(position="innermost")

    async def before_model_request(
        self, ctx: RunContext[Any], request_context: ModelRequestContext
    ) -> ModelRequestContext:
        session = _current.get()
        if session is not None:
            session.note_model_request(request_context)
        return request_context

    async def after_model_request(
        self,
        ctx: RunContext[Any],
        *,
        request_context: ModelRequestContext,
        response: ModelResponse,
    ) -> ModelResponse:
        session = _current.get()
        if session is not None:
            session.note_model_response(request_context, response)
        return response

    async def on_model_request_error(
        self,
        ctx: RunContext[Any],
        *,
        request_context: ModelRequestContext,
        error: Exception,
    ) -> ModelResponse:
        session = _current.get()
        if session is not None:
            session.note_model_error(request_context, error)
        raise error

    async def before_tool_execute(
        self,
        ctx: RunContext[Any],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        session = _current.get()
        if session is not None:
            session.note_tool_call(call, args)
        return args

    async def after_tool_execute(
        self,
        ctx: RunContext[Any],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict[str, Any],
        result: Any,
    ) -> Any:
        session = _current.get()
        if session is not None:
            session.note_tool_result(call, result)
        return result

    async def on_tool_execute_error(
        self,
        ctx: RunContext[Any],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict[str, Any],
        error: Exception,
    ) -> Any:
        session = _current.get()
        if session is not None:
            session.note_tool_error(call, error)
        raise error


__all__ = [
    "AgentTraceCapability",
    "TraceSession",
    "current_session",
    "finish_trace",
    "mark_trace",
    "note_rejection",
    "note_steering",
    "output_kind_of",
    "safe_value",
    "start_trace",
    "trace_scope",
]
