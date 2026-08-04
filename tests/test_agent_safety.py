"""Agent safety helpers (kmua.plugins.agent.safety) contracts.

Secret masking must rewrite credentials out of text before the model or the
chat sees them (tool returns, agent replies) while leaving structured parts
untouched; user input is deliberately never modified. Usage ceilings must map
config to pydantic-ai UsageLimits; tool-output limits must be configurable and
disable-able; capability assembly must follow the config switches.
"""

from __future__ import annotations

from datetime import timedelta

from pydantic_ai_harness.guardrails import ToolResultInfo

from kmua.config import app_config
from kmua.plugins.agent import safety

_FAKE_KEY = "sk-abcdefghijklmnopqrstuvwxyz1234567890"


def _result_info(result: object) -> ToolResultInfo:
    return ToolResultInfo(name="read", args={}, tool_call_id="1", result=result)


# ---- secret masking: tool results ----


def test_scrub_tool_result_redacts_credentials():
    result = safety.scrub_tool_result(_result_info(f"token: {_FAKE_KEY}"))
    assert result.action == "replace"
    assert result.replacement is not None
    assert _FAKE_KEY not in result.replacement


def test_scrub_tool_result_passes_clean_text():
    result = safety.scrub_tool_result(_result_info("no secrets here"))
    assert result.action == "allow"


def test_scrub_tool_result_skips_non_text():
    assert safety.scrub_tool_result(_result_info({"key": _FAKE_KEY})).action == "allow"
    assert safety.scrub_tool_result(_result_info(b"\x89PNG")).action == "allow"


def test_scrub_tool_result_disabled(monkeypatch):
    monkeypatch.setattr(app_config, "agent_secret_masking", False)
    result = safety.scrub_tool_result(_result_info(f"token: {_FAKE_KEY}"))
    assert result.action == "allow"


# ---- secret masking: output ----


def test_scrub_output_redacts_text_and_skips_structured():
    result = safety.scrub_output(f"here is my {_FAKE_KEY}")
    assert result.action == "replace"
    assert _FAKE_KEY not in (result.replacement or "")
    assert safety.scrub_output(42).action == "allow"


# ---- usage ceilings ----


def test_build_usage_limits_from_config():
    limits = safety.build_usage_limits()
    assert limits is not None
    assert limits.request_limit == app_config.agent_usage_request_limit
    assert limits.tool_calls_limit == app_config.agent_usage_tool_calls_limit
    assert limits.total_tokens_limit == app_config.agent_usage_total_tokens_limit


def test_build_usage_limits_none_when_all_disabled(monkeypatch):
    monkeypatch.setattr(app_config, "agent_usage_request_limit", 0)
    monkeypatch.setattr(app_config, "agent_usage_tool_calls_limit", 0)
    monkeypatch.setattr(app_config, "agent_usage_total_tokens_limit", 0)
    assert safety.build_usage_limits() is None


# ---- tool output limits ----


def test_build_tool_output_limits_spills_by_default():
    limits = safety.build_tool_output_limits()
    assert limits is not None
    assert len(limits.bands) == 1
    assert limits.bands[0].over == app_config.agent_tool_output_limit
    assert limits.strip_ansi is True
    # Default mode: lossless spill with a bounded truncation fallback and a
    # TTL-pruned store under the cache dir.
    from pydantic_ai_harness.tool_output_limits import Spill

    assert isinstance(limits.bands[0].action, Spill)
    assert limits.bands[0].action.then is not None
    assert limits.store is not None
    assert limits.store.base_dir == app_config.cachedir / "overflow"
    assert limits.store.cleanup_after == timedelta(hours=6)


def test_build_tool_output_limits_truncate_only_when_spill_off(monkeypatch):
    monkeypatch.setattr(app_config, "agent_tool_output_spill", False)
    limits = safety.build_tool_output_limits()
    assert limits is not None
    from pydantic_ai_harness.tool_output_limits import Truncate

    assert isinstance(limits.bands[0].action, Truncate)
    assert limits.store is None


def test_build_tool_output_limits_disabled(monkeypatch):
    monkeypatch.setattr(app_config, "agent_tool_output_limit", 0)
    assert safety.build_tool_output_limits() is None


# ---- capability assembly ----


async def _fake_history_processor(ctx, messages):  # noqa: ANN001
    return messages


def test_build_agent_capabilities_follows_switches(monkeypatch):
    caps = safety.build_agent_capabilities(_fake_history_processor)
    kinds = {type(c).__name__ for c in caps}
    assert "ProcessHistory" in kinds
    assert "ToolGuardrail" in kinds
    assert "OutputGuardrail" in kinds
    assert "ToolOutputLimits" in kinds
    # Always-on context guards (runaway generations, near-limit warnings).
    assert "ClampOversizedMessages" in kinds
    assert "WarnNearLimits" in kinds

    monkeypatch.setattr(app_config, "agent_secret_masking", False)
    monkeypatch.setattr(app_config, "agent_tool_output_limit", 0)
    caps = safety.build_agent_capabilities(_fake_history_processor)
    kinds = {type(c).__name__ for c in caps}
    assert kinds == {
        "ProcessHistory",
        "ClampOversizedMessages",
        "WarnNearLimits",
    }
