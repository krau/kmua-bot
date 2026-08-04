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

    Spill mode (default) persists the full payload to a local store under the
    cache dir and hands the model a ``read_tool_result`` handle, so it can
    page through or grep the original instead of living with a clamp; a
    bounded truncation is only the fallback when the store write fails.
    ``agent_tool_output_spill=False`` restores pure truncation (no read-back).
    """
    over = app_config.agent_tool_output_limit
    if over <= 0:
        return None
    truncate = Truncate(max_chars=app_config.agent_tool_output_max_chars)
    if app_config.agent_tool_output_spill:
        store: LocalFileStore | None = LocalFileStore(
            base_dir=app_config.cachedir / "overflow",
            cleanup_after=timedelta(hours=6),
        )
        action: Action = Spill(then=truncate)
    else:
        store = None
        action = truncate
    return ToolOutputLimits(
        bands=[Band(over=over, action=action)],
        strip_ansi=True,
        store=store,
    )


def build_agent_capabilities(
    history_processor: Any,
) -> list[Any]:
    """Assemble the main agent's capabilities from config.

    ``ProcessHistory`` is always present (core); the harness safety
    capabilities follow the ``agent_secret_masking`` /
    ``agent_tool_output_limit`` switches.
    """
    caps: list[Any] = [ProcessHistory(history_processor)]
    if app_config.agent_secret_masking:
        caps.append(ToolGuardrail(result_guard=scrub_tool_result))
        caps.append(OutputGuardrail(guard=scrub_output))
    limits = build_tool_output_limits()
    if limits is not None:
        caps.append(limits)
    # Runaway-generation guard: clamp a single oversized response text or
    # tool-call args before the next request can exceed the context cap.
    caps.append(ClampOversizedMessages(max_part_tokens=50_000))
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
