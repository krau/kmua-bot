from __future__ import annotations

from types import SimpleNamespace

import pytest
from loguru import logger
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from kmua.plugins.agent.model_log import ModelActivityLog


@pytest.fixture
def log_records():
    records: list[str] = []
    sink_id = logger.add(records.append, level="DEBUG")
    try:
        yield records
    finally:
        logger.remove(sink_id)


async def test_model_activity_logged_end_to_end(log_records):
    async def echo(x: str) -> str:
        return x

    agent = Agent(
        TestModel(
            call_tools=["echo"],
            custom_output_text="done",
        ),
        capabilities=[ModelActivityLog()],
        tools=[echo],
    )
    await agent.run("hello", deps=SimpleNamespace(user_id=42, chat_id=-100))

    joined = "\n".join(log_records)
    assert "model request" in joined
    assert "model response" in joined
    assert "user 42 in chat -100" in joined
    assert "tools=echo(" in joined
    assert 'text="done"' in joined


async def test_model_activity_logs_request_shape(log_records):
    """The request line reports history size and pending tool returns."""

    def noop() -> str:
        return "ok"

    agent = Agent(
        TestModel(call_tools=["noop"]),
        capabilities=[ModelActivityLog()],
        tools=[noop],
    )
    result = await agent.run("hi")
    await agent.run("again", message_history=result.all_messages())

    request_lines = [r for r in log_records if "model request" in r]
    assert len(request_lines) >= 2
    # The follow-up request carries the previous tool return in history.
    assert any("tool_returns=1" in r for r in request_lines)


async def test_model_activity_truncates_long_input(log_records):
    """Long user input is truncated, not dumped in full."""

    agent = Agent(
        TestModel(),
        capabilities=[ModelActivityLog()],
    )
    await agent.run("x" * 10_000)

    joined = "\n".join(log_records)
    assert "x" * 10_000 not in joined
    assert "..." in joined
