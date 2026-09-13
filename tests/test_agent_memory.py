"""Cross-group user memory recording & formatting contracts."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.usefixtures("initialised_db")


@pytest.fixture
async def memory_format():
    # Imported lazily: the module pulls in the agent graph, which spawns
    # background tasks at import time (needs a running loop).
    from kmua.plugins.agent.memory import AgentMessage, format_user_messages

    return AgentMessage, format_user_messages


def _msg(AgentMessage, chat_id: int, chat_name: str, is_group: bool, text: str):
    return AgentMessage(
        chat_id=chat_id,
        chat_name=chat_name,
        is_group=is_group,
        date=datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
        text=text,
    )


async def test_format_empty_input(memory_format):
    _, fmt = memory_format
    assert fmt([]) == ""


async def test_format_groups_by_chat_keeping_first_seen_order(memory_format):
    AgentMessage, fmt = memory_format
    messages = [
        _msg(AgentMessage, -1001, "群A", True, "hello"),
        _msg(AgentMessage, 1, "", False, "私聊1"),
        _msg(AgentMessage, -1002, "群B", True, "world"),
        _msg(AgentMessage, -1001, "群A", True, "again"),
        _msg(AgentMessage, 1, "", False, "私聊2"),
    ]
    lines = fmt(messages).split("\n")
    assert lines[0].startswith("用户与 AI 的聊天记录")
    assert lines[1] == "[群聊「群A」]"
    assert lines[2] == "  2026-08-01 10:00 hello"
    assert lines[3] == "  2026-08-01 10:00 again"
    assert lines[4] == "[私聊]"
    assert lines[5] == "  2026-08-01 10:00 私聊1"
    assert lines[6] == "  2026-08-01 10:00 私聊2"
    assert lines[7] == "[群聊「群B」]"
    assert lines[8] == "  2026-08-01 10:00 world"


async def test_format_collapses_newlines_in_text(memory_format):
    AgentMessage, fmt = memory_format
    msg = _msg(AgentMessage, -1001, "群A", True, "第一行\n第二行")
    lines = fmt([msg]).split("\n")
    assert len(lines) == 3
    assert lines[2] == "  2026-08-01 10:00 第一行 第二行"


async def test_memory_handlers_use_distinct_dispatcher_groups():
    from kmua.plugins.agent import memory

    handlers = (
        memory.record_memory,
        memory.record_agent_memory,
        memory.record_group_memory,
    )
    groups = [
        {group for _, group in getattr(handler, "handlers", ())} for handler in handlers
    ]

    assert all(len(handler_groups) == 1 for handler_groups in groups)
    assert len({next(iter(handler_groups)) for handler_groups in groups}) == len(
        handlers
    )


async def test_group_memory_chunks_large_batches(monkeypatch):
    from kmua.plugins.agent import memory

    class FakePowerMem:
        def __init__(self):
            self.calls = []

        async def add(self, text, **kwargs):
            self.calls.append((text, kwargs))
            return {"results": [{"id": len(self.calls)}]}

    fake = FakePowerMem()
    chat_id = -910001
    group_key = memory.state.group_messages_key(chat_id)
    update_key = memory.state.group_memory_update_key(chat_id)
    monkeypatch.setattr(memory.app_config, "agent", True)
    monkeypatch.setattr(memory.app_config, "agent_group_memory", True)
    monkeypatch.setattr(memory.app_config, "agent_model_timeout", 0)
    monkeypatch.setattr(memory, "powermemory", fake)
    monkeypatch.setattr(memory, "is_chat_allowed", lambda _: True)

    async def chat_config(_):
        return SimpleNamespace(ai_reply=True, group_memory_enabled=True)

    monkeypatch.setattr(memory.database, "get_chat_config", chat_config)
    await memory.memttlcache.delete(group_key)
    await memory.memttlcache.delete(update_key)
    try:
        for message_id in range(1, 102):
            await memory.record_group_memory(
                None,
                SimpleNamespace(
                    id=message_id,
                    text=f"正常群聊消息 {message_id} " + "内容" * 20,
                    caption=None,
                    from_user=SimpleNamespace(
                        id=1001, full_name="测试用户", is_bot=False
                    ),
                    chat=SimpleNamespace(id=chat_id),
                    date=None,
                ),
            )
        assert len(fake.calls) > 1
        assert all(
            len(text) <= memory._GROUP_MEMORY_MAX_CHARS for text, _ in fake.calls
        )
        combined = "\n".join(text for text, _ in fake.calls)
        assert "正常群聊消息 1" in combined
        assert "正常群聊消息 101" in combined
        assert await memory.memttlcache.get(group_key) == []
        assert await memory.memttlcache.get(update_key) is True
        assert all(kwargs["user_id"] == f"group_{chat_id}" for _, kwargs in fake.calls)
    finally:
        await memory.memttlcache.delete(group_key)
        await memory.memttlcache.delete(update_key)


async def test_group_memory_failure_preserves_batch(monkeypatch):
    from kmua.plugins.agent import memory

    class FailingPowerMem:
        async def add(self, text, **kwargs):
            raise RuntimeError("provider unavailable")

    chat_id = -910002
    group_key = memory.state.group_messages_key(chat_id)
    update_key = memory.state.group_memory_update_key(chat_id)
    monkeypatch.setattr(memory.app_config, "agent", True)
    monkeypatch.setattr(memory.app_config, "agent_group_memory", True)
    monkeypatch.setattr(memory.app_config, "agent_model_timeout", 0)
    monkeypatch.setattr(memory, "powermemory", FailingPowerMem())
    monkeypatch.setattr(memory, "is_chat_allowed", lambda _: True)

    async def chat_config(_):
        return SimpleNamespace(ai_reply=True, group_memory_enabled=True)

    monkeypatch.setattr(memory.database, "get_chat_config", chat_config)
    await memory.memttlcache.delete(group_key)
    await memory.memttlcache.delete(update_key)
    try:
        for message_id in range(1, 102):
            await memory.record_group_memory(
                None,
                SimpleNamespace(
                    id=message_id,
                    text=f"失败重试消息 {message_id}",
                    caption=None,
                    from_user=SimpleNamespace(
                        id=1001, full_name="测试用户", is_bot=False
                    ),
                    chat=SimpleNamespace(id=chat_id),
                    date=None,
                ),
            )
        pending = await memory.memttlcache.get(group_key)
        assert len(pending) == 100
        assert await memory.memttlcache.get(update_key) is None
    finally:
        await memory.memttlcache.delete(group_key)
        await memory.memttlcache.delete(update_key)


async def test_group_memory_update_is_single_flight_per_chat(monkeypatch):
    from kmua.plugins.agent import memory

    class BlockingPowerMem:
        def __init__(self):
            self.calls = []
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def add(self, text, **kwargs):
            self.calls.append(text)
            self.started.set()
            await self.release.wait()
            return {}

    fake = BlockingPowerMem()
    chat_id = -910003
    group_key = memory.state.group_messages_key(chat_id)
    update_key = memory.state.group_memory_update_key(chat_id)
    monkeypatch.setattr(memory.app_config, "agent", True)
    monkeypatch.setattr(memory.app_config, "agent_group_memory", True)
    monkeypatch.setattr(memory.app_config, "agent_model_timeout", 0)
    monkeypatch.setattr(memory, "powermemory", fake)
    monkeypatch.setattr(memory, "is_chat_allowed", lambda _: True)

    async def chat_config(_):
        return SimpleNamespace(ai_reply=True, group_memory_enabled=True)

    monkeypatch.setattr(memory.database, "get_chat_config", chat_config)

    def message(message_id: int):
        return SimpleNamespace(
            id=message_id,
            text=f"并发消息 {message_id}",
            caption=None,
            from_user=SimpleNamespace(id=1001, full_name="测试用户", is_bot=False),
            chat=SimpleNamespace(id=chat_id),
            date=None,
        )

    await memory.memttlcache.delete(group_key)
    await memory.memttlcache.delete(update_key)
    try:
        await memory.memttlcache.set(
            group_key,
            [
                memory.GroupMessage(
                    chat_id=chat_id,
                    message_id=i,
                    text=f"历史消息 {i}",
                    sender_name="测试用户",
                    sender_id=1001,
                    date=datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
                )
                for i in range(1, 101)
            ],
        )
        first = asyncio.create_task(memory.record_group_memory(None, message(101)))
        await asyncio.wait_for(fake.started.wait(), timeout=5)
        # A concurrent worker handling the next message of the same chat must
        # not start a second update while the first one is still running.
        second = asyncio.create_task(memory.record_group_memory(None, message(102)))
        await asyncio.wait_for(second, timeout=5)
        fake.release.set()
        await asyncio.wait_for(first, timeout=5)
        # Only the first batch was stored; the concurrent message was dropped.
        assert fake.calls
        assert all("并发消息 102" not in text for text in fake.calls)
    finally:
        await memory.memttlcache.delete(group_key)
        await memory.memttlcache.delete(update_key)


async def test_a_memory_update_is_billed_to_the_message_that_triggered_it(monkeypatch):
    """记忆抽取是独立的一次模型调用, 不在任何主回合的 usage 里。

    它由某条消息触发, 于是按那条消息的身份结算 —— 不记的话这段开销在 /quota 和面板
    上都看不到。
    """
    from pydantic_ai.usage import RunUsage

    from kmua import database
    from kmua.config import app_config
    from kmua.plugins.agent import datatype, quota, user_memory

    class _MemoryAgent:
        async def run(self, **_kwargs):
            return SimpleNamespace(
                output=datatype.UserMemoryResult(
                    **dict.fromkeys(
                        (
                            "disposition",
                            "interests",
                            "doings",
                            "works",
                            "wishes",
                            "worries",
                            "skills",
                            "attitudes_to_model",
                            "experiences_with_model",
                            "extra_info",
                            "affection_change_amplitude",
                        ),
                        None,
                    ),
                    affection_option="no_change",
                ),
                usage=RunUsage(input_tokens=640, output_tokens=160),
            )

    monkeypatch.setattr(app_config, "agent_model_timeout", 0, raising=False)
    subject = quota.Subject(user_id=9311, chat_id=-1009311000, in_group=True)
    day = database.utc_day()
    before = await database.get_usage(database.SCOPE_CHAT, subject.chat_id, day)

    await user_memory.update_user_memory(
        _MemoryAgent(), "聊天记录", subject.user_id, subject
    )

    after = await database.get_usage(database.SCOPE_CHAT, subject.chat_id, day)
    assert after[0] == before[0] + 1
    assert (after[2] - before[2], after[3] - before[3]) == (640, 160)
    assert (await database.get_usage(database.SCOPE_USER, subject.user_id, day))[
        2
    ] == 640
