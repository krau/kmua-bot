"""Cross-group user memory recording & formatting contracts."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest


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
