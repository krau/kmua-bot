"""Agent safety helpers (kmua.plugins.agent.safety) contracts.

Secret masking must rewrite credentials out of text before the model or the
chat sees them (tool returns, agent replies) while leaving structured parts
untouched; user input is deliberately never modified. Usage ceilings must map
config to pydantic-ai UsageLimits; tool-output limits must be configurable and
disable-able; capability assembly must follow the config switches.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

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
    # The store is session-scoped; the underlying file store keeps the TTL.
    assert limits.store._inner.base_dir == app_config.cachedir / "overflow"
    assert limits.store._inner.cleanup_after == timedelta(hours=6)


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
    assert "_SilentToolOutputLimits" in kinds
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


async def test_read_spill_handle_via_read_tool(tmp_path, monkeypatch):
    """The spill reader is folded into `read` (spill:// protocol); it is
    implemented locally over the public OverflowStore protocol, not extracted
    from harness internals."""
    monkeypatch.setattr(app_config, "cachedir", tmp_path)
    safety.build_agent_capabilities(_fake_history_processor)
    from pydantic_ai_harness.tool_output_limits import LocalFileStore

    from kmua.plugins.agent.tools import io

    store = LocalFileStore(base_dir=tmp_path / "overflow")
    handle = await store.write("k", b"line1\nline2\nline3")
    ctx = SimpleNamespace(deps=SimpleNamespace())

    first = await io.read(ctx, f"spill://{handle}", start_line=1, max_lines=10)
    assert "line1" in first and "line2" in first
    paged = await io.read(ctx, f"spill://{handle}", start_line=2, max_lines=10)
    assert "line2" in paged and "line1" not in paged


def test_clamp_threshold_scales_with_window(monkeypatch):
    monkeypatch.setattr(app_config, "agent_context_window_tokens", 128_000)
    monkeypatch.setattr(app_config, "agent_clamp_max_part_ratio", 0.4)
    caps = safety.build_agent_capabilities(_fake_history_processor)
    clamp = next(c for c in caps if type(c).__name__ == "ClampOversizedMessages")
    assert clamp.max_part_tokens == 51_200

    # A smaller-window model tightens the guard automatically.
    monkeypatch.setattr(app_config, "agent_context_window_tokens", 32_000)
    caps = safety.build_agent_capabilities(_fake_history_processor)
    clamp = next(c for c in caps if type(c).__name__ == "ClampOversizedMessages")
    assert clamp.max_part_tokens == 12_800


def test_clamp_fallback_when_window_unset(monkeypatch):
    monkeypatch.setattr(app_config, "agent_context_window_tokens", 0)
    caps = safety.build_agent_capabilities(_fake_history_processor)
    clamp = next(c for c in caps if type(c).__name__ == "ClampOversizedMessages")
    assert clamp.max_part_tokens == 50_000


def test_silent_tool_output_limits_registers_no_tool(monkeypatch):
    """The read_tool_result tool must not be registered; the subclass returns
    None from the capability protocol hook instead of monkeypatching."""
    limits = safety.build_tool_output_limits()
    assert limits is not None
    assert limits.get_toolset() is None
    assert type(limits).__name__ == "_SilentToolOutputLimits"


async def test_read_spill_line_cap_matches_read_tool(tmp_path, monkeypatch):
    """The spill branch must honor the read tool's documented max_lines
    ceiling (1500), not a smaller internal cap."""
    monkeypatch.setattr(app_config, "cachedir", tmp_path)
    safety.build_agent_capabilities(_fake_history_processor)
    from pydantic_ai_harness.tool_output_limits import LocalFileStore

    from kmua.plugins.agent.tools import io

    store = LocalFileStore(base_dir=tmp_path / "overflow")
    payload = "\n".join(f"line{i}" for i in range(1, 601)).encode()
    handle = await store.write("k", payload)
    ctx = SimpleNamespace(deps=SimpleNamespace())

    result = await io.read(ctx, f"spill://{handle}", start_line=1, max_lines=600)
    assert "line1" in result and "line600" in result
    assert result.count("\n") >= 599  # all 600 lines survived


async def test_spill_scoped_to_session(tmp_path, monkeypatch):
    """A spill written in one session must be unreadable from another, and
    readable again within the same session."""
    monkeypatch.setattr(app_config, "cachedir", tmp_path)
    safety.build_agent_capabilities(_fake_history_processor)
    from kmua.plugins.agent.tools import io

    token_a = safety.set_spill_session("c_1")
    handle = await safety._spill_store.write("k", b"secret of c1")
    safety.reset_spill_session(token_a)
    ctx = SimpleNamespace(deps=SimpleNamespace())

    # Same session can read it back.
    token_a2 = safety.set_spill_session("c_1")
    try:
        result = await io.read(ctx, f"spill://{handle}")
        assert "secret of c1" in result
    finally:
        safety.reset_spill_session(token_a2)

    # Another session is rejected even with the exact handle.
    token_b = safety.set_spill_session("c_2")
    try:
        result = await io.read(ctx, f"spill://{handle}")
        assert "secret of c1" not in result
        assert "unavailable" in result
    finally:
        safety.reset_spill_session(token_b)


async def test_delete_spill_session_removes_payloads(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "cachedir", tmp_path)
    safety.build_agent_capabilities(_fake_history_processor)

    token = safety.set_spill_session("c_9")
    handle = await safety._spill_store.write("k", b"forget me")
    safety.reset_spill_session(token)

    safety.delete_spill_session("c_9")
    token2 = safety.set_spill_session("c_9")
    try:
        from kmua.plugins.agent.tools import io

        result = await io.read(
            SimpleNamespace(deps=SimpleNamespace()), f"spill://{handle}"
        )
        assert "forget me" not in result
    finally:
        safety.reset_spill_session(token2)
