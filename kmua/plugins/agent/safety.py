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
from datetime import timedelta
from typing import Any

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

from .model_log import ModelActivityLog

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
    Spill mode registers the harness's read_tool_result tool for paging the
    original payload back; truncation-only mode never spills. The store is
    session-scoped, so handles are only readable from their own conversation.
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
    return ToolOutputLimits(
        bands=[Band(over=over, action=action)],
        strip_ansi=True,
        store=store,
    )


# Spill payloads follow the conversation lifecycle: written under the current
# (chat, user) session prefix, unreadable from any other session, deleted by
# /forget.
_spill_session_ctx: ContextVar[str | None] = ContextVar(
    "kmua_spill_session", default=None
)


def set_spill_session(session: str) -> Token[str | None]:
    """Bind the current task's spill session (set by the runner around runs)."""
    return _spill_session_ctx.set(session)


def reset_spill_session(token: Token[str | None]) -> None:
    _spill_session_ctx.reset(token)


class _SessionScopedOverflowStore:
    """OverflowStore that scopes every payload to the current session.

    ``write`` prefixes the harness-generated key with the session, so handles
    carry their session; ``read`` rejects handles outside the current
    session's prefix. Both require a bound session: unbound access is
    refused, never unscoped, so no payload can be written or read without an
    owner.
    """

    def __init__(self, inner: LocalFileStore) -> None:
        self._inner = inner

    async def write(self, key: str, data: bytes) -> str:
        session = _spill_session_ctx.get()
        if not session:
            raise OSError("spill write requires a bound session")
        return await self._inner.write(f"{session}/{key}", data)

    async def read(self, handle: str) -> bytes:
        session = _spill_session_ctx.get()
        if not session:
            raise OSError("spill read requires a bound session")
        if not handle.startswith(f"{session}/"):
            raise OSError(f"handle {handle!r} is not in this session")
        return await self._inner.read(handle)


def delete_spill_session(session: str) -> None:
    """Delete every spilled payload bound to a session (/forget clears the
    conversation, so its spills must go with it)."""
    store = build_tool_output_limits()
    if store is None or not isinstance(store.store, _SessionScopedOverflowStore):
        return
    base_dir = store.store._inner.base_dir
    if base_dir is None:
        return
    target = base_dir / session
    shutil.rmtree(target, ignore_errors=True)


def _clamp_max_part_tokens() -> int:
    """Single-part clamp threshold: a fraction of the context window, so a
    smaller-window model tightens the guard automatically. Falls back to a
    fixed 50k when the window is unset (compaction disabled)."""
    window = app_config.agent_context_window_tokens
    if window > 0:
        return max(1, int(window * app_config.agent_clamp_max_part_ratio))
    return 50_000


def build_agent_capabilities(history_processor: Any) -> list[Any]:
    """Assemble the main agent's capabilities from config.

    ``ProcessHistory`` is always present; the safety capabilities follow the
    ``agent_secret_masking`` / ``agent_tool_output_limit`` switches; spill
    mode registers the harness's read_tool_result tool.
    """
    caps: list[Any] = [ProcessHistory(history_processor), ModelActivityLog()]
    if app_config.agent_secret_masking:
        caps.append(ToolGuardrail(result_guard=scrub_tool_result))
        caps.append(OutputGuardrail(guard=scrub_output))
    limits = build_tool_output_limits()
    if limits is not None:
        caps.append(limits)
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
    "scrub_output",
    "scrub_tool_result",
]
