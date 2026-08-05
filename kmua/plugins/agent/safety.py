"""Agent safety helpers: credential masking and per-run usage ceilings.

Secret masking is built on the pydantic-ai-harness guardrail detectors: vendor
API keys, tokens, and whole private-key blocks are rewritten out of text
before they reach the model (tool returns) or the chat (reply). Redaction
rather than refusal is deliberate - the run keeps working, the secret just
never enters the model context or message history. User input is deliberately
left untouched.

Usage ceilings are pydantic-ai ``UsageLimits``, applied to every main-agent
run so a runaway tool-call loop or an over-long task fails fast instead of
burning tokens.
"""

from __future__ import annotations

import shutil
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from pydantic_ai import ModelRetry
from pydantic_ai.capabilities import ProcessHistory
from pydantic_ai.usage import UsageLimits
from pydantic_ai_harness.compaction import ClampOversizedMessages, WarnNearLimits
from pydantic_ai_harness.guardrails import (
    GuardrailResult,
    OutputGuardrail,
    ToolGuardrail,
    ToolResultInfo,
)
from pydantic_ai_harness.guardrails.detectors import for_text, redact_secrets
from pydantic_ai_harness.tool_output_limits import (
    Action,
    Band,
    LocalFileStore,
    Spill,
    ToolOutputLimits,
    Truncate,
)

from kmua.config import app_config
from kmua.logger import logger

_scrub_text_output = for_text(redact_secrets, on_other="allow")


def scrub_tool_result(info: ToolResultInfo) -> GuardrailResult:
    """Redact credentials from a tool return before the model sees it.

    Only text returns are rewritten; a structured return (or a binary one) is
    left untouched, since substituting a string for it would change its type.
    """
    if not app_config.agent_secret_masking or not isinstance(info.result, str):
        return GuardrailResult.allow()
    return redact_secrets(info.result)


def scrub_output(output: object) -> GuardrailResult:
    """Redact credentials from the agent reply before it reaches the chat."""
    if not app_config.agent_secret_masking:
        return GuardrailResult.allow()
    return _scrub_text_output(output)


def build_usage_limits() -> UsageLimits | None:
    """Per-run usage ceilings for the main agent; 0/None disables a limit."""
    limits = UsageLimits(
        request_limit=app_config.agent_usage_request_limit or None,
        tool_calls_limit=app_config.agent_usage_tool_calls_limit or None,
        total_tokens_limit=app_config.agent_usage_total_tokens_limit or None,
    )
    if (
        limits.request_limit is None
        and limits.tool_calls_limit is None
        and limits.total_tokens_limit is None
    ):
        return None
    return limits


def build_tool_output_limits() -> ToolOutputLimits | None:
    """Tool-return reduction for the main agent; None when disabled.
    Returns the silent subclass, so no read_tool_result tool is registered.
    """
    over = app_config.agent_tool_output_limit
    if over <= 0:
        return None
    truncate = Truncate(max_chars=app_config.agent_tool_output_max_chars)
    if app_config.agent_tool_output_spill:
        inner = LocalFileStore(
            base_dir=app_config.cachedir / "overflow",
            cleanup_after=timedelta(hours=6),
        )
        store: _SessionScopedOverflowStore | None = _SessionScopedOverflowStore(inner)
        action: Action = Spill(then=truncate)
    else:
        store = None
        action = truncate
    return _SilentToolOutputLimits(
        bands=[Band(over=over, action=action)],
        strip_ansi=True,
        store=store,
    )


@dataclass
class _SilentToolOutputLimits(ToolOutputLimits):
    """ToolOutputLimits that does not register its read_tool_result tool.

    kmua folds spill reading into its own `read` tool (spill:// protocol) so
    the model faces one tool instead of two. The overflow logic and the spill
    store stay fully active; only the model-facing tool is suppressed, by
    overriding the capability protocol hook ``get_toolset()`` to return None
    (a legal return - the core ToolSearch capability does the same when its
    corpus is empty).

    WHY a subclass instead of poking at the internals: an earlier version
    extracted the tool's closure from ``get_toolset().tools[...].function``
    and monkeypatched ``get_toolset`` on the instance. Both touch harness
    internals (FunctionToolset layout, instance-attribute shadowing) that can
    change on any 0.x release. This version depends only on the public
    capability protocol (``AbstractCapability.get_toolset``) plus the public
    ``OverflowStore`` protocol, and implements the slice/pattern logic itself.
    When upgrading pydantic-ai-harness, re-check: (1) ``get_toolset`` is still
    the tool-registration hook, (2) ``OverflowStore.read`` semantics
    (handle → bytes, OSError on unknown handle).
    """

    def get_toolset(self) -> None:  # type: ignore[override]
        return None


# Session binding for spilled payloads: kmua's conversations have no durable
# session object - the per-(chat, user) history is the session, cleared by
# /forget. Spilled payloads must follow the same lifecycle: they are written
# under a session prefix captured from the running agent's context and become
# unreadable from any other session, and /forget deletes the whole prefix.
_spill_session_ctx: ContextVar[str | None] = ContextVar(
    "kmua_spill_session", default=None
)


def set_spill_session(session: str) -> Token[str | None]:
    """Bind the current task's spill session (set by the runner around runs)."""
    return _spill_session_ctx.set(session)


def reset_spill_session(token: Token[str | None]) -> None:
    _spill_session_ctx.reset(token)


class _SessionScopedOverflowStore:
    """OverflowStore wrapper that scopes every payload to the current session.

    ``write`` prefixes the harness-generated key with the session captured
    from the context var, so handles carry their session; ``read`` rejects any
    handle that is not under the current session's prefix, so a model in one
    conversation cannot read another conversation's spilled payload even with
    a guessed handle. Outside an agent run (no context var) writes stay
    unscoped, matching the harness behavior.
    """

    def __init__(self, inner: LocalFileStore) -> None:
        self._inner = inner

    async def write(self, key: str, data: bytes) -> str:
        session = _spill_session_ctx.get()
        if session:
            key = f"{session}/{key}"
        return await self._inner.write(key, data)

    async def read(self, handle: str) -> bytes:
        session = _spill_session_ctx.get()
        if session and not handle.startswith(f"{session}/"):
            raise OSError(f"handle {handle!r} is not in this session")
        return await self._inner.read(handle)


def delete_spill_session(session: str) -> None:
    """Delete every spilled payload bound to a session (/forget clears the
    conversation, so its spills must go with it)."""
    store = _spill_store
    if store is None:
        return
    base_dir = store._inner.base_dir
    if base_dir is None:
        return
    target = base_dir / session
    shutil.rmtree(target, ignore_errors=True)


# The spill store the read tool pages through; set whenever the capability is
# built with spill mode enabled.
_spill_store: _SessionScopedOverflowStore | None = None

# Must match the read tool's max_lines ceiling (io.py): the spill:// branch
# reuses the read tool's start_line/max_lines parameters, so a silent lower
# cap here would contradict the tool's documented range.
_MAX_READ_LINES = 1500
_MAX_READ_CHARS = 50_000


async def _read_spill(
    store: _SessionScopedOverflowStore,
    handle: str,
    offset: int,
    limit: int,
    from_end: bool,
    pattern: str | None,
) -> str:
    """Read a slice of a spilled payload, mirroring read_tool_result's
    semantics (bounded in both axes; pattern is a literal substring, never a
    regex, so a model-supplied value cannot hang the host)."""
    if offset < 0:
        raise ModelRetry("`offset` must be >= 0.")
    if limit < 1:
        raise ModelRetry("`limit` must be >= 1.")
    limit = min(limit, _MAX_READ_LINES)
    try:
        data = await store.read(handle)
    except OSError:
        return (
            f"Spilled payload for handle '{handle}' is unavailable (wrong "
            "handle or already pruned). Use a handle from an overflowed tool "
            "return."
        )
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if from_end:
        lines = list(reversed(lines))
    if pattern:
        lines = [line for line in lines if pattern in line]
    selected = lines[offset : offset + limit]
    joined = "\n".join(selected)
    if len(joined) > _MAX_READ_CHARS:
        joined = joined[:_MAX_READ_CHARS] + "\n...[truncated]"
    return joined


def get_spill_reader() -> Any | None:
    """A (ctx, handle, offset, limit, from_end, pattern) callable over the
    configured spill store, or None when spill reading is unavailable."""
    if _spill_store is None:
        if app_config.agent_tool_output_limit <= 0:
            reason = "agent_tool_output_limit = 0"
        elif not app_config.agent_tool_output_spill:
            reason = "agent_tool_output_spill = false"
        else:
            reason = "capabilities not initialized"
        logger.debug(f"spill reader unavailable: {reason}")
        return None

    async def reader(
        ctx: Any,
        handle: str,
        offset: int = 0,
        limit: int = 200,
        from_end: bool = False,
        pattern: str | None = None,
    ) -> str:
        return await _read_spill(_spill_store, handle, offset, limit, from_end, pattern)  # type: ignore[arg-type]

    return reader if _spill_store is not None else None


def _clamp_max_part_tokens() -> int:
    """Single-part clamp threshold: a fraction of the model's context window,
    so switching to a smaller-window model tightens the guard automatically.
    Falls back to a fixed 50k when the window is unset (compaction disabled)."""
    window = app_config.agent_context_window_tokens
    if window > 0:
        return max(1, int(window * app_config.agent_clamp_max_part_ratio))
    return 50_000


def build_agent_capabilities(history_processor: Any) -> list[Any]:
    """Assemble the main agent's capabilities from config.

    ``ProcessHistory`` is always present (core); the harness safety
    capabilities follow the ``agent_secret_masking`` /
    ``agent_tool_output_limit`` switches; the harness tool closure (spill
    reading) is folded into kmua's ``read`` tool and not registered.
    """
    global _spill_store
    caps: list[Any] = [ProcessHistory(history_processor)]
    if app_config.agent_secret_masking:
        caps.append(ToolGuardrail(result_guard=scrub_tool_result))
        caps.append(OutputGuardrail(guard=scrub_output))
    limits = build_tool_output_limits()
    if limits is not None:
        _spill_store = (
            limits.store
            if isinstance(limits.store, _SessionScopedOverflowStore)
            else None
        )
        caps.append(limits)
    else:
        _spill_store = None
    # Runaway-generation guard: clamp a single oversized response text or
    # tool-call args before the next request can exceed the context cap.
    caps.append(ClampOversizedMessages(max_part_tokens=_clamp_max_part_tokens()))
    # Warn the model to wrap up as the per-run usage ceilings approach, so a
    # long task concludes instead of being hard-cut by UsageLimits.
    caps.append(
        WarnNearLimits(
            max_iterations=app_config.agent_usage_request_limit or None,
            max_total_tokens=app_config.agent_usage_total_tokens_limit or None,
        )
    )
    return caps


__all__ = [
    "build_agent_capabilities",
    "build_tool_output_limits",
    "build_usage_limits",
    "get_spill_reader",
    "scrub_output",
    "scrub_tool_result",
]
