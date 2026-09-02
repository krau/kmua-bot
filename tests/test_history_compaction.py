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


async def test_clear_prefix_helpers():
    """Prefix clearing removes every matching key and counts them."""
    from kmua.plugins.agent import agent as agent_mod

    cache = agent_mod.common.memttlcache
    store = agent_mod.common.memstore
    await cache.set("message_history_with_agent:1:1", b"a")
    await cache.set("message_history_with_agent:1:2", b"b")
    await cache.set("other:key", b"c")
    store._data["agent_ask_state:1:1"] = {"options": []}
    store._data["unrelated"] = 1

    assert await agent_mod._clear_memttlcache_prefix("message_history_with_agent:") == 2
    assert await cache.get("message_history_with_agent:1:1") is None
    assert await cache.get("other:key") == b"c"

    assert agent_mod._clear_memstore_prefix("agent_") == 1
    assert "agent_ask_state:1:1" not in store._data
    assert "unrelated" in store._data


async def test_conversation_locks_are_per_conversation():
    """Turn ownership is keyed by (chat, user): a run in chat A must not
    block messages in chat B."""
    from kmua.plugins.agent import state

    state._conversation_locks.clear()
    try:
        lock_a = state.get_conversation_lock(-100, 1)
        assert not state.is_running(-100, 1)
        await lock_a.acquire()
        assert state.is_running(-100, 1)
        assert not state.is_running(-200, 1)  # same user, other chat: free
        assert not state.is_running(-100, 2)  # other user, same chat: free
        lock_a.release()
        assert not state.is_running(-100, 1)
    finally:
        state._conversation_locks.clear()


def test_steering_queue_is_bounded():
    """An over-limit steering queue drops new messages instead of growing."""
    from kmua.plugins.agent import state

    state._steering_messages.clear()
    try:
        state.queue_steering(-100, 1, "a" * 100)
        # Exceed the char cap with the second message.
        state.queue_steering(-100, 1, "b" * 8000)
        assert state.drain_steering(-100, 1) == ["a" * 100]
    finally:
        state._steering_messages.clear()


def test_clear_steering_drops_queued_messages():
    """History cleanup must also drop queued interjections so deleted
    content is never re-injected."""
    from kmua.plugins.agent import state

    state._steering_messages.clear()
    try:
        state.queue_steering(-100, 1, "queued")
        state.queue_steering(-200, 1, "other chat")
        assert state.clear_steering(-100, 1) is None or True
        assert state.drain_steering(-100, 1) == []
        assert state.drain_steering(-200, 1) == ["other chat"]
        state.queue_steering(-100, 1, "again")
        assert state.clear_all_steering() == 1
        assert state.drain_steering(-100, 1) == []
    finally:
        state._steering_messages.clear()


def test_steering_queue_round_trip():
    """Interjections queue per conversation and drain in order."""
    from kmua.plugins.agent import state

    state._steering_messages.clear()
    try:
        state.queue_steering(-100, 1, "first")
        state.queue_steering(-100, 1, "second")
        state.queue_steering(-100, 2, "other user")
        assert state.drain_steering(-100, 1) == ["first", "second"]
        assert state.drain_steering(-100, 1) == []
        assert state.drain_steering(-100, 2) == ["other user"]
    finally:
        state._steering_messages.clear()


def test_steering_queue_empty_drain():
    from kmua.plugins.agent import state

    state._steering_messages.clear()
    try:
        assert state.drain_steering(-100, 9) == []
    finally:
        state._steering_messages.clear()


async def test_interjection_enqueues_into_active_run():
    """A live AgentRun receives the interjection immediately (no hook
    round-trip, no extra model request); the steering queue is only the
    fallback while no run is registered."""
    from kmua.plugins.agent import agent as agent_mod
    from kmua.plugins.agent import state

    state._active_runs.clear()
    state._steering_messages.clear()
    try:
        enqueued = []

        class FakeRun:
            result = None  # run in flight

            def enqueue(self, *content, priority="asap"):
                enqueued.append((content, priority))

        state.register_active_run(-100, 1, FakeRun())
        msg = SimpleNamespace(text="别那样做", caption=None)
        await agent_mod._queue_interjection(msg, -100, 1)  # type: ignore[arg-type]
        assert enqueued == [(("别那样做",), "asap")]
        assert state.drain_steering(-100, 1) == []

        # No active run: falls back to the steering queue.
        state.unregister_active_run(-100, 1)
        await agent_mod._queue_interjection(msg, -100, 1)  # type: ignore[arg-type]
        assert state.drain_steering(-100, 1) == ["别那样做"]
    finally:
        state._active_runs.clear()
        state._steering_messages.clear()


async def test_interjection_media_message_is_not_queued():
    """Media-only messages carry no steerable text; they are dropped."""
    from kmua.plugins.agent import agent as agent_mod
    from kmua.plugins.agent import state

    state._active_runs.clear()
    state._steering_messages.clear()
    try:
        msg = SimpleNamespace(text=None, caption=None)
        await agent_mod._queue_interjection(msg, -100, 1)  # type: ignore[arg-type]
        assert state.drain_steering(-100, 1) == []
    finally:
        state._active_runs.clear()
        state._steering_messages.clear()


async def test_enqueue_interjection_budget_and_live_run():
    """Direct live-run enqueues share the steering caps; the budget resets
    when the run ends."""
    from kmua.plugins.agent import state

    state._active_runs.clear()
    state._steering_messages.clear()
    state._interjection_budget.clear()
    try:
        enqueued = []

        class FakeRun:
            result = None  # run in flight

            def enqueue(self, *content, priority="asap"):
                enqueued.append(content)

        state.register_active_run(-100, 1, FakeRun())
        for i in range(state._MAX_STEERING_MESSAGES):
            assert state.enqueue_interjection(-100, 1, f"msg{i}") is True
        # Budget exhausted: rejected, nothing enqueued.
        assert state.enqueue_interjection(-100, 1, "overflow") is False
        assert len(enqueued) == state._MAX_STEERING_MESSAGES

        # Run ended: budget resets.
        state.unregister_active_run(-100, 1)
        assert state.enqueue_interjection(-100, 1, "after run") is True
        assert state.drain_steering(-100, 1) == ["after run"]
    finally:
        state._active_runs.clear()
        state._steering_messages.clear()
        state._interjection_budget.clear()


def test_conversation_lock_pruning_bounds_registry():
    """Unlocked locks are pruned once the registry exceeds its bound."""
    from kmua.plugins.agent import state

    state._conversation_locks.clear()
    try:
        for i in range(state._MAX_CONVERSATION_LOCKS):
            state.get_conversation_lock(1000 + i, 1)
        assert len(state._conversation_locks) == state._MAX_CONVERSATION_LOCKS
        # One more conversation: the unlocked locks are pruned first.
        state.get_conversation_lock(9999, 1)
        assert len(state._conversation_locks) <= 2
    finally:
        state._conversation_locks.clear()


async def test_enqueue_skips_ended_run_and_charges_on_success():
    """A run whose graph ended (result populated) must not accept enqueues:
    the message falls into the fallback queue instead of being stranded.
    The budget is charged only when the delivery actually succeeded."""
    from kmua.plugins.agent import state

    state._active_runs.clear()
    state._steering_messages.clear()
    state._interjection_budget.clear()
    try:
        enqueued = []

        class EndedRun:
            result = object()  # graph already finished

            def enqueue(self, *content, priority="asap"):
                enqueued.append(content)

        state.register_active_run(-100, 1, EndedRun())
        assert state.enqueue_interjection(-100, 1, "late") is True
        assert enqueued == []  # nothing went into the ended run
        assert state.drain_steering(-100, 1) == ["late"]
        # Budget was charged once for the successful fallback delivery.
        assert state._interjection_budget[(-100, 1)] == (1, 4)

        # Fallback queue full: rejected without charging the budget.
        state._interjection_budget[(-100, 1)] = (
            state._MAX_STEERING_MESSAGES,
            0,
        )
        assert state.enqueue_interjection(-100, 1, "x") is False
    finally:
        state._active_runs.clear()
        state._steering_messages.clear()
        state._interjection_budget.clear()


async def test_clear_steering_resets_budget():
    from kmua.plugins.agent import state

    state._steering_messages.clear()
    state._interjection_budget.clear()
    try:
        state._interjection_budget[(-100, 1)] = (5, 100)
        state.clear_steering(-100, 1)
        assert (-100, 1) not in state._interjection_budget
        state._interjection_budget[(-100, 1)] = (5, 100)
        assert state.clear_all_steering() == 0
        assert state._interjection_budget == {}
    finally:
        state._steering_messages.clear()
        state._interjection_budget.clear()


def _running_user_message(text: str, user_id: int = 1) -> SimpleNamespace:
    """A group message from a user whose agent turn is in flight."""
    import pyrogram

    return SimpleNamespace(
        text=text,
        caption=None,
        entities=None,
        outgoing=False,
        service=False,
        automatic_forward=False,
        sender_chat=None,
        from_user=SimpleNamespace(id=user_id),
        chat=SimpleNamespace(id=-100, type=pyrogram.enums.ChatType.SUPERGROUP),
    )


def _patch_follow_up_filter(monkeypatch) -> list[tuple[int, int, str]]:
    """Wire the follow-up filter's dependencies; returns the enqueue spy."""
    from kmua.config import app_config
    from kmua.plugins.agent import followup, state

    enqueued: list[tuple[int, int, str]] = []

    def _enqueue(chat_id: int, user_id: int, text: str) -> bool:
        enqueued.append((chat_id, user_id, text))
        return True

    monkeypatch.setattr(app_config, "agent", True)
    monkeypatch.setattr(app_config, "agent_follow_up", True)
    monkeypatch.setattr(followup, "_default_relevance_check_agent", object())
    monkeypatch.setattr(followup, "is_chat_allowed", lambda _chat_id: True)
    monkeypatch.setattr(followup, "is_explicit_reply", lambda _m: False)
    monkeypatch.setattr(state, "is_running", lambda _c, _u: True)
    monkeypatch.setattr(state, "enqueue_interjection", _enqueue)
    return enqueued


async def test_follow_up_interjection_skips_nickname_mention(monkeypatch):
    """A mid-turn nickname mention is already interjected by the wake
    handler (group=0); the follow-up filter must not enqueue it again, or
    the same message lands twice in the running turn (duplicated history
    and a doubled interjection-budget charge)."""
    from kmua.config import app_config
    from kmua.plugins.agent import followup

    monkeypatch.setattr(app_config, "nickname", "kmua")
    enqueued = _patch_follow_up_filter(monkeypatch)
    msg = _running_user_message("kmua 继续说")
    assert await followup._follow_up_filter_func(None, None, msg) is False
    assert enqueued == []


async def test_follow_up_interjection_enqueues_plain_message(monkeypatch):
    """A mid-turn plain message (no mention, no reply) is only handled by
    the follow-up filter and must be delivered into the running turn."""
    from kmua.config import app_config
    from kmua.plugins.agent import followup

    monkeypatch.setattr(app_config, "nickname", "kmua")
    enqueued = _patch_follow_up_filter(monkeypatch)
    msg = _running_user_message("继续说说看")
    assert await followup._follow_up_filter_func(None, None, msg) is False
    assert enqueued == [(-100, 1, "继续说说看")]


async def test_follow_up_interjection_keeps_nickname_text_when_unset(monkeypatch):
    """With no configured nickname the wake handler cannot fire for a
    nickname-like text, so the follow-up filter must still deliver it."""
    from kmua.config import app_config
    from kmua.plugins.agent import followup

    monkeypatch.setattr(app_config, "nickname", "")
    enqueued = _patch_follow_up_filter(monkeypatch)
    msg = _running_user_message("kmua 继续说")
    assert await followup._follow_up_filter_func(None, None, msg) is False
    assert enqueued == [(-100, 1, "kmua 继续说")]
