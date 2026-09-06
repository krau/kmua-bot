"""Typing keepalive: starts at agent trigger and is reused by the runner."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pyrogram.enums

from kmua.config import app_config
from kmua.plugins.agent import runner
from kmua.plugins.agent.output import TypingKeepAlive


class _FakeClient:
    def __init__(self) -> None:
        self.actions: list[tuple] = []

    async def send_chat_action(self, chat_id: int, action) -> None:  # type: ignore[no-untyped-def]
        self.actions.append((chat_id, action))


def _message(chat_id: int = -100123) -> SimpleNamespace:
    return SimpleNamespace(chat=SimpleNamespace(id=chat_id), guest_query_id=None)


async def test_typing_keepalive_sends_immediately_on_start():
    client = _FakeClient()
    keepalive = TypingKeepAlive(client, _message())  # type: ignore[arg-type]
    await keepalive.__aenter__()
    await asyncio.sleep(0.05)
    assert client.actions
    assert client.actions[0][1] == pyrogram.enums.ChatAction.TYPING
    await keepalive.__aexit__(None, None, None)
    assert keepalive._task is not None and keepalive._task.done()


async def test_run_agent_forwards_caller_keepalive(monkeypatch):
    captured: dict = {}

    async def fake_impl(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(runner, "_run_agent_impl", fake_impl)
    monkeypatch.setattr(app_config, "agent_run_timeout", 0)
    keepalive = SimpleNamespace()
    await runner.run_agent(  # type: ignore[arg-type]
        agi=object(),  # type: ignore[arg-type]
        client=_FakeClient(),  # type: ignore[arg-type]
        message=_message(),  # type: ignore[arg-type]
        user_id=1,
        chat_id=-100123,
        user_prompt=[],
        history=[],
        deps=SimpleNamespace(),
        multimodal_model=None,
        model=None,
        lang="zh",
        typing_keepalive=keepalive,  # type: ignore[arg-type]
    )
    assert captured["typing_keepalive"] is keepalive
