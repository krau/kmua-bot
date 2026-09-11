"""Typing keepalive: starts at agent trigger and is reused by the runner."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pyrogram.enums
import pytest

from kmua.config import app_config
from kmua.plugins.agent import quota, runner
from kmua.plugins.agent.output import TypingKeepAlive

# `run_agent` touches the quota tables, so the schema must exist.
pytestmark = pytest.mark.usefixtures("initialised_db")


class _FakeClient:
    def __init__(self) -> None:
        self.actions: list[tuple] = []

    async def send_chat_action(self, chat_id: int, action) -> None:  # type: ignore[no-untyped-def]
        self.actions.append((chat_id, action))


def _message(chat_id: int = -100123) -> SimpleNamespace:
    return SimpleNamespace(chat=SimpleNamespace(id=chat_id))


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
        subject=quota.Subject(user_id=1, chat_id=-100123, in_group=True),
        typing_keepalive=keepalive,  # type: ignore[arg-type]
    )
    assert captured["typing_keepalive"] is keepalive


async def test_run_agent_stops_typing_before_timeout_reply(monkeypatch):
    async def stalled_impl(**kwargs):
        await asyncio.sleep(10)

    class _ReplyMessage:
        chat = SimpleNamespace(id=-100123)

        def __init__(self):
            self.replies: list[str] = []

        async def reply_text(self, text: str, **kwargs):
            self.replies.append(text)

    monkeypatch.setattr(runner, "_run_agent_impl", stalled_impl)
    monkeypatch.setattr(app_config, "agent_run_timeout", 0.01)
    client = _FakeClient()
    message = _ReplyMessage()
    keepalive = TypingKeepAlive(client, message)  # type: ignore[arg-type]
    await keepalive.__aenter__()

    await runner.run_agent(  # type: ignore[arg-type]
        agi=object(),
        client=client,  # type: ignore[arg-type]
        message=message,  # type: ignore[arg-type]
        user_id=1,
        chat_id=-100123,
        user_prompt=[],
        history=[],
        deps=SimpleNamespace(),
        multimodal_model=None,
        model=None,
        lang="zh",
        subject=quota.Subject(user_id=1, chat_id=-100123, in_group=True),
        typing_keepalive=keepalive,
    )

    assert len(message.replies) == 1
    assert "Timeout" in message.replies[0]
    assert keepalive._task is not None and keepalive._task.done()
