"""Compaction summary model-request contracts."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from pydantic_ai import CallToolsNode
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.usage import RunUsage
from pydantic_graph import End

from kmua.plugins.agent.history import InPlaceSummarizingCompaction


class _FakeRun:
    def __init__(self, nodes: list[object], output: str = "summary") -> None:
        self._nodes = nodes
        self.result = SimpleNamespace(output=output)
        self.usage = RunUsage()

    async def __aiter__(self):
        for node in self._nodes:
            yield node


class _FakeAgent:
    def __init__(self, run: _FakeRun) -> None:
        self.run = run
        self.kwargs: dict[str, object] = {}

    @asynccontextmanager
    async def iter(self, **kwargs):
        self.kwargs = kwargs
        yield self.run


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(
        usage=RunUsage(),
        deps=SimpleNamespace(instructions="SYS"),
        model=object(),
    )


async def test_summary_uses_gateway_compatible_tool_choice() -> None:
    fake_agent = _FakeAgent(_FakeRun([End(data=None)]))
    compaction = InPlaceSummarizingCompaction(agent=fake_agent)

    summary = await compaction._summarize([], _ctx())

    assert summary == "summary"
    assert fake_agent.kwargs["model_settings"] == {"tool_choice": "auto"}
    assert "Do not call any tools" in fake_agent.kwargs["user_prompt"]


async def test_summary_aborts_before_executing_a_tool_call() -> None:
    tool_call = ToolCallPart(
        tool_name="write",
        args={"path": "unexpected.txt", "content": "nope"},
        tool_call_id="call-1",
    )
    fake_agent = _FakeAgent(_FakeRun([CallToolsNode(ModelResponse(parts=[tool_call]))]))
    compaction = InPlaceSummarizingCompaction(agent=fake_agent)

    with pytest.raises(RuntimeError, match="refusing to execute"):
        await compaction._summarize([], _ctx())
