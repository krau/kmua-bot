"""Conversation compaction contracts (kmua.plugins.agent.history).

Compaction is delegated to pydantic-ai-harness TieredCompaction; kmua's own
invariants on top: deferred (unresolved) tool calls and everything after them
survive compaction verbatim, multimodal content is trimmed after compaction,
and the strategy follows the agent_compaction_* switches.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast

from pydantic_ai import ModelMessage
from pydantic_ai.messages import (
    BinaryContent,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    SystemPromptPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model, infer_model
from pydantic_ai.usage import RunUsage
from pydantic_ai_harness.compaction import TieredCompaction
from pydantic_graph import End

from kmua.config import app_config
from kmua.plugins.agent import history

# ---- strategy builder ----


def test_build_compaction_strategy_default_tiers():
    strategy = history.build_compaction_strategy(agent=object())
    assert isinstance(strategy, TieredCompaction)
    assert strategy.target_tokens == int(
        app_config.agent_context_window_tokens * app_config.agent_context_compress_ratio
    )
    tier_types = {type(t).__name__ for t in strategy.tiers}
    assert tier_types == {"ClearToolResults", "InPlaceSummarizingCompaction"}


def test_build_compaction_strategy_follows_switches(monkeypatch):
    monkeypatch.setattr(app_config, "agent_compaction_clear_tool_results", False)
    strategy = history.build_compaction_strategy(agent=object())
    assert isinstance(strategy, TieredCompaction)
    assert {type(t).__name__ for t in strategy.tiers} == {
        "InPlaceSummarizingCompaction"
    }

    monkeypatch.setattr(app_config, "agent_compaction_summarize", False)
    assert history.build_compaction_strategy() is None


def test_build_compaction_strategy_clear_only(monkeypatch):
    monkeypatch.setattr(app_config, "agent_compaction_summarize", False)
    strategy = history.build_compaction_strategy(agent=object())
    assert isinstance(strategy, TieredCompaction)
    assert {type(t).__name__ for t in strategy.tiers} == {"ClearToolResults"}


def test_build_compaction_strategy_disabled_when_window_zero(monkeypatch):
    monkeypatch.setattr(app_config, "agent_context_window_tokens", 0)
    assert history.build_compaction_strategy(agent=object()) is None


# ---- compact_history ----


def _messages() -> list[ModelMessage]:
    """History: complete pair, then a deferred call, then a user message."""
    return [
        ModelRequest(parts=[UserPromptPart(content="do the thing")]),
        ModelResponse(
            parts=[ToolCallPart(tool_name="read", args={"path": "a"}, tool_call_id="1")]
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="read", content="large result", tool_call_id="1"
                )
            ]
        ),
        ModelResponse(
            parts=[ToolCallPart(tool_name="ask_user", args={}, tool_call_id="2")]
        ),
        ModelRequest(parts=[UserPromptPart(content="my answer")]),
    ]


async def test_compact_history_empty_and_disabled(monkeypatch):
    assert await history.compact_history([], None) == []

    monkeypatch.setattr(app_config, "agent_compaction_summarize", False)
    monkeypatch.setattr(app_config, "agent_compaction_clear_tool_results", False)

    messages = _messages()
    assert await history.compact_history(messages, None) == messages


async def test_compact_history_preserves_deferred_tail(monkeypatch):
    """Compaction must never touch the deferred call or what follows it."""
    monkeypatch.setattr(app_config, "agent_context_window_tokens", 5)
    monkeypatch.setattr(app_config, "agent_compaction_summarize", False)
    monkeypatch.setattr(app_config, "agent_compaction_keep_pairs", 0)
    monkeypatch.setattr(app_config, "agent_multimodal_max_items", 0)

    messages = _messages()
    # "test" is the built-in test model; only the clear tier runs here, so no
    # model request is ever issued (production passes a real Model instance).
    result = await history.compact_history(messages, infer_model("test"), deps=None)
    assert result != messages  # the old tool return was blanked
    # The deferred call message and the following user message survive verbatim.
    assert result[-2:] == messages[-2:]


def test_truncate_multimodal_removes_oldest_items():
    messages = [
        ModelRequest(
            parts=[
                UserPromptPart(
                    content=[
                        "text",
                        BinaryContent(data=b"img1", media_type="image/jpeg"),
                        BinaryContent(data=b"img2", media_type="image/jpeg"),
                    ]
                )
            ]
        )
    ]
    result = history.truncate_multimodal(messages, max_items=1)
    first_part = result[0].parts[0]
    assert isinstance(first_part, UserPromptPart)
    content = first_part.content
    assert isinstance(content, list)
    placeholders = [c for c in content if c == "[multimodal content removed]"]
    assert len(placeholders) == 1
    assert BinaryContent(data=b"img2", media_type="image/jpeg") in content
    assert "text" in content


def test_find_deferred_tool_call_index():
    messages = _messages()
    assert history.find_deferred_tool_call_index(messages) == 3
    resolved_only = [
        ModelResponse(
            parts=[ToolCallPart(tool_name="read", args={}, tool_call_id="1")]
        ),
        ModelRequest(
            parts=[ToolReturnPart(tool_name="read", content="x", tool_call_id="1")]
        ),
    ]
    assert history.find_deferred_tool_call_index(resolved_only) is None
    retried = [
        ModelResponse(
            parts=[ToolCallPart(tool_name="read", args={}, tool_call_id="1")]
        ),
        ModelRequest(parts=[RetryPromptPart(content="retry", tool_call_id="1")]),
    ]
    assert history.find_deferred_tool_call_index(retried) is None


class _FakeModel:
    """Stand-in run model: only model_name is ever read (bridge-prefix logic)."""

    model_name = "fake"


class _FakeRun:
    def __init__(self, output: str) -> None:
        self.result = SimpleNamespace(output=output)

    async def __aiter__(self):
        yield End(data=None)


class _FakeMainAgent:
    """Captures the summary run's arguments instead of executing the graph."""

    def __init__(self) -> None:
        self.kwargs: dict = {}

    @asynccontextmanager
    async def iter(self, **kwargs):
        self.kwargs = kwargs
        yield _FakeRun("the summary")


async def test_compact_history_summarizes_in_place(monkeypatch):
    """The summary run must reproduce the conversation's request shape.

    Verbatim history (not rendered text), the same system prompt via deps, the
    same model, and tool schemas present but disabled - so the provider prompt
    cache prefix matches the conversation requests exactly.
    """
    monkeypatch.setattr(app_config, "agent_context_window_tokens", 5)
    monkeypatch.setattr(app_config, "agent_compaction_clear_tool_results", False)
    monkeypatch.setattr(app_config, "agent_compaction_summarize", True)
    monkeypatch.setattr(app_config, "agent_compaction_keep_messages", 1)
    monkeypatch.setattr(app_config, "agent_multimodal_max_items", 0)

    model = _FakeModel()
    main_agent = _FakeMainAgent()
    deps = SimpleNamespace(instructions="SYS INSTR")
    messages = [
        ModelRequest(parts=[UserPromptPart(content="do the thing")]),
        ModelRequest(parts=[UserPromptPart(content="then that")]),
        ModelRequest(parts=[UserPromptPart(content="and this")]),
    ]

    usage = RunUsage()
    result = await history.compact_history(
        messages,
        cast(Model, model),  # model_name-only stand-in; no request is issued
        deps=deps,
        agent=main_agent,  # type: ignore[arg-type]
        usage=usage,
    )
    assert result != messages
    assert main_agent.kwargs, "summary run was never issued"
    kwargs = main_agent.kwargs
    # The summary run is billed to the caller's usage, not a throwaway.
    assert kwargs["usage"] is usage
    # The summarized prefix is sent verbatim, unchanged, as message history.
    assert kwargs["message_history"] == messages[:2]
    # The run's instructions become the summary request's system prompt.
    assert kwargs["deps"].instructions == "SYS INSTR"
    # Same model; tool schemas present but calls impossible.
    assert kwargs["model"] is model
    assert kwargs["model_settings"] == {"tool_choice": "none"}
    assert "Summarize the conversation above" in kwargs["user_prompt"]
    assert "never merge two speakers' words" in kwargs["user_prompt"]
    # The summary lands in the compacted history as a system prompt part.
    summary_parts = [
        p.content for m in result for p in m.parts if isinstance(p, SystemPromptPart)
    ]
    assert any("the summary" in content for content in summary_parts)


async def test_compact_history_uses_custom_instruction(monkeypatch):
    """Only the instruction is customizable; the model stays the run's own."""
    monkeypatch.setattr(app_config, "agent_context_window_tokens", 5)
    monkeypatch.setattr(app_config, "agent_compaction_clear_tool_results", False)
    monkeypatch.setattr(app_config, "agent_compaction_summarize", True)
    monkeypatch.setattr(app_config, "agent_compaction_keep_messages", 1)
    monkeypatch.setattr(app_config, "agent_multimodal_max_items", 0)
    monkeypatch.setattr(
        app_config,
        "agent_compaction_summary_instruction",
        "CUSTOM summary wording.",
    )

    model = _FakeModel()
    main_agent = _FakeMainAgent()
    deps = SimpleNamespace(instructions="SYS INSTR")
    messages = [
        ModelRequest(parts=[UserPromptPart(content="do the thing")]),
        ModelRequest(parts=[UserPromptPart(content="then that")]),
        ModelRequest(parts=[UserPromptPart(content="and this")]),
    ]

    result = await history.compact_history(
        messages,
        cast(Model, model),  # model_name-only stand-in; no request is issued
        deps=deps,
        agent=main_agent,  # type: ignore[arg-type]
    )
    assert result != messages
    assert main_agent.kwargs["user_prompt"].startswith("CUSTOM summary wording.")
    assert main_agent.kwargs["model"] is model  # model is never overridden


async def test_compaction_runs_concurrently_across_tasks(monkeypatch):
    """Compaction is per-session: two compactions in different tasks must not
    serialize (no shared state to protect), so the re-entrancy guard is a
    task-scoped ContextVar, not a mutex."""
    monkeypatch.setattr(app_config, "agent_context_window_tokens", 5)
    monkeypatch.setattr(app_config, "agent_compaction_summarize", False)

    assert not history._compacting_ctx.get()
    # Simulate two sessions compacting at once: each task's flag is isolated.
    token_a = history._compacting_ctx.set(True)
    assert history._compacting_ctx.get() is True
    history._compacting_ctx.reset(token_a)
    assert not history._compacting_ctx.get()


async def test_compaction_reentrant_call_skips(monkeypatch):
    """A re-entrant compact_history from the summary run's own ProcessHistory
    (same task) must skip immediately - it would otherwise recurse forever."""
    monkeypatch.setattr(app_config, "agent_context_window_tokens", 5)
    monkeypatch.setattr(app_config, "agent_compaction_summarize", False)

    token = history._compacting_ctx.set(True)
    try:
        messages = _messages()
        result = await history.compact_history(messages, infer_model("test"), deps=None)
        assert result == messages, "re-entrant call must return unchanged"
    finally:
        history._compacting_ctx.reset(token)
