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

import pytest
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
    assert isinstance(result.replacement, str)
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
    replacement = result.replacement or ""
    assert isinstance(replacement, str)
    assert _FAKE_KEY not in replacement
    assert safety.scrub_output(42).action == "allow"


# ---- usage ceilings ----


def test_build_usage_limits_defaults_to_none():
    """Usage limits are unrestricted by default; only explicit config caps."""
    assert safety.build_usage_limits() is None


def test_build_usage_limits_from_config(monkeypatch):
    monkeypatch.setattr(app_config, "agent_usage_request_limit", 50)
    monkeypatch.setattr(app_config, "agent_usage_tool_calls_limit", 150)
    monkeypatch.setattr(app_config, "agent_usage_total_tokens_limit", 600_000)
    limits = safety.build_usage_limits()
    assert limits is not None
    assert limits.request_limit == 50
    assert limits.tool_calls_limit == 150
    assert limits.total_tokens_limit == 600_000


def test_build_usage_limits_none_when_all_disabled(monkeypatch):
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
    assert isinstance(limits.store, safety._SessionScopedOverflowStore)
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
    assert "ToolOutputLimits" in kinds
    # Always-on context guards (runaway generations). No usage ceilings are
    # configured by default, so no near-limit warning capability is mounted.
    assert "ClampOversizedMessages" in kinds
    assert "WarnNearLimits" not in kinds

    monkeypatch.setattr(app_config, "agent_usage_request_limit", 50)
    monkeypatch.setattr(app_config, "agent_usage_total_tokens_limit", 600_000)
    caps = safety.build_agent_capabilities(_fake_history_processor)
    kinds = {type(c).__name__ for c in caps}
    assert "WarnNearLimits" in kinds

    monkeypatch.setattr(app_config, "agent_secret_masking", False)
    monkeypatch.setattr(app_config, "agent_tool_output_limit", 0)
    caps = safety.build_agent_capabilities(_fake_history_processor)
    kinds = {type(c).__name__ for c in caps}
    assert kinds == {
        "ProcessHistory",
        "ModelActivityLog",
        "SteeringInjection",
        "ClampOversizedMessages",
        "WarnNearLimits",
    }


async def _make_spill_store(tmp_path, monkeypatch):
    """A session-scoped spill store wired exactly as the agent gets it."""
    monkeypatch.setattr(app_config, "cachedir", tmp_path)
    limits = safety.build_tool_output_limits()
    assert limits is not None
    assert isinstance(limits.store, safety._SessionScopedOverflowStore)
    return limits.store


async def test_spill_scoped_to_session(tmp_path, monkeypatch):
    """A spill written in one session must be unreadable from another, and
    readable again within the same session."""
    store = await _make_spill_store(tmp_path, monkeypatch)

    token_a = safety.set_spill_session("c_1")
    handle = await store.write("k", b"secret of c1")
    safety.reset_spill_session(token_a)

    token_a2 = safety.set_spill_session("c_1")
    try:
        data = await store.read(handle)
        assert b"secret of c1" in data
    finally:
        safety.reset_spill_session(token_a2)

    token_b = safety.set_spill_session("c_2")
    try:
        with pytest.raises(OSError):
            await store.read(handle)
    finally:
        safety.reset_spill_session(token_b)


async def test_spill_delete_session_removes_payloads(tmp_path, monkeypatch):
    store = await _make_spill_store(tmp_path, monkeypatch)

    token = safety.set_spill_session("c_9")
    handle = await store.write("k", b"forget me")
    safety.reset_spill_session(token)

    safety.delete_spill_session("c_9")
    token2 = safety.set_spill_session("c_9")
    try:
        with pytest.raises(OSError):
            await store.read(handle)
    finally:
        safety.reset_spill_session(token2)


async def test_spill_requires_bound_session(tmp_path, monkeypatch):
    """Without a bound spill session, reads and writes are refused: no
    payload may be written or read without an owner."""
    store = await _make_spill_store(tmp_path, monkeypatch)

    with pytest.raises(OSError):
        await store.write("k", b"data")
    with pytest.raises(OSError):
        await store.read("any/handle")


async def test_spill_preview_names_read_tool_result(tmp_path, monkeypatch):
    """End-to-end: an oversized tool return spilled by the real capability
    hands the model a read_tool_result handle with the original payload, and
    the model can page it back through the registered tool."""
    monkeypatch.setattr(app_config, "cachedir", tmp_path)
    from pydantic_ai import Agent
    from pydantic_ai.models.test import TestModel

    def big_output() -> str:
        return "x" * 12_000

    limits = safety.build_tool_output_limits()
    assert limits is not None
    agent = Agent(
        TestModel(call_tools=["big_output"]),
        capabilities=[limits],
        tools=[big_output],
    )
    token = safety.set_spill_session("c_preview")
    try:
        result = await agent.run("run it")
    finally:
        safety.reset_spill_session(token)
    messages = result.all_messages()
    preview = ""
    for msg in messages:
        for part in msg.parts:
            if part.part_kind == "tool-return" and part.tool_name == "big_output":
                preview = str(part.content)
    assert preview, "spilled tool return not found"
    assert "read_tool_result" in preview
    assert "handle=" in preview

    # The same run's context can page the spilled payload back through the
    # registered tool.
    import re

    from pydantic_ai import Agent as AgentCls
    from pydantic_ai.models.test import TestModel as TM

    match = re.search(r"handle='([^']+)'", preview)
    assert match, "no handle in preview"
    handle = match.group(1)

    class _HandleReaderModel(TM):
        def gen_tool_args(self, tool_def):  # noqa: ANN001
            return {"handle": handle, "limit": 3}

    assert limits is not None
    reader = AgentCls(
        _HandleReaderModel(call_tools=["read_tool_result"]),
        capabilities=[limits],
        tools=[big_output],
    )
    token2 = safety.set_spill_session("c_preview")
    try:
        result2 = await reader.run("read it")
    finally:
        safety.reset_spill_session(token2)
    text = "".join(
        str(part.content)
        for msg in result2.all_messages()
        for part in msg.parts
        if part.part_kind == "tool-return" and part.tool_name == "read_tool_result"
    )
    assert "xxx" in text


async def test_clear_all_spills_removes_every_session(tmp_path, monkeypatch):
    store = await _make_spill_store(tmp_path, monkeypatch)

    token_a = safety.set_spill_session("c_1")
    await store.write("k", b"one")
    safety.reset_spill_session(token_a)
    token_b = safety.set_spill_session("c_2")
    await store.write("k", b"two")
    safety.reset_spill_session(token_b)

    assert safety.clear_all_spills() == 2

    for session in ("c_1", "c_2"):
        token = safety.set_spill_session(session)
        try:
            with pytest.raises(OSError):
                await store.read("k")
        finally:
            safety.reset_spill_session(token)


async def test_steering_injection_folds_into_next_request():
    """Queued interjections are appended to the very next model request -
    the mid-turn injection point pydantic-ai re-reads before every call."""
    from pydantic_ai import Agent
    from pydantic_ai.models.test import TestModel

    from kmua.plugins.agent import state
    from kmua.plugins.agent.safety import SteeringInjection

    state._steering_messages.clear()
    try:
        agent = Agent(
            TestModel(),
            capabilities=[SteeringInjection()],
        )
        state.queue_steering(-100, 1, "别下载了, 直接分析文本")
        result = await agent.run(
            "处理这个文件",
            deps=SimpleNamespace(chat_id=-100, user_id=1),
        )
        joined = " ".join(
            str(part.content)
            for msg in result.all_messages()
            for part in msg.parts
            if part.part_kind == "user-prompt"
        )
        assert "别下载了, 直接分析文本" in joined
        assert state.drain_steering(-100, 1) == []
    finally:
        state._steering_messages.clear()


async def test_steering_injection_empty_queue_passthrough():
    from pydantic_ai import Agent
    from pydantic_ai.models.test import TestModel

    from kmua.plugins.agent.safety import SteeringInjection

    agent = Agent(
        TestModel(custom_output_text="ok"),
        capabilities=[SteeringInjection()],
    )
    result = await agent.run("hi", deps=SimpleNamespace(chat_id=-100, user_id=1))
    texts = [
        str(part.content)
        for msg in result.all_messages()
        for part in msg.parts
        if part.part_kind == "user-prompt"
    ]
    assert texts == ["hi"]
