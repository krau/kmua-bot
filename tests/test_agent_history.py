"""Agent chat history fetch: selector semantics of get_history_messages.

The reply-chain selector walks a message's ancestors one hop at a time via
its ``reply_to`` header (no single API call returns the whole chain), so the
tool returns the full chain without the model guessing id ranges.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

from pydantic_ai import RunContext, RunUsage
from pydantic_ai.models.test import TestModel

from kmua.common.tgmethod import HistoryMessage
from kmua.plugins.agent import datatype
from kmua.plugins.agent.tools import bot


def _ctx(message_id: int = 100) -> RunContext[datatype.ContextDeps]:
    return cast(
        RunContext[datatype.ContextDeps],
        SimpleNamespace(
            deps=SimpleNamespace(
                client=SimpleNamespace(),
                chat_id=-100_123,
                user_id=1001,
                message=SimpleNamespace(id=message_id),
                powermemory=None,
            ),
            model=TestModel(),
            usage=RunUsage(),
            messages=[],
        ),
    )


def _fake_fetch(captured: dict, monkeypatch):
    async def fake_user(user_id):
        return SimpleNamespace(full_name=f"User {user_id}")

    monkeypatch.setattr(bot.database, "get_user_by_id", fake_user)

    async def fake(chat_id, message_ids, replies=1):
        captured.update(chat_id=chat_id, message_ids=message_ids)
        return [
            HistoryMessage(
                message_id=i,
                chat_id=chat_id,
                user_id=1001,
                text=f"msg {i}",
                time=datetime.now(UTC),
            )
            for i in message_ids
        ]

    return fake


async def test_latest_default_window(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        bot.common, "get_messages_with_cache", _fake_fetch(captured, monkeypatch)
    )
    result = await bot.get_history_messages(_ctx(message_id=100))
    # latest 50 ending at the current message, inclusive
    assert captured["message_ids"] == list(range(51, 101))
    assert "100 messages" in result or "msg 100" in result


async def test_before_excludes_anchor(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        bot.common, "get_messages_with_cache", _fake_fetch(captured, monkeypatch)
    )
    await bot.get_history_messages(_ctx(), before=100, count=5)
    # the 5 messages immediately before 100: 95..99, anchor itself excluded
    assert captured["message_ids"] == [95, 96, 97, 98, 99]


async def test_after_excludes_anchor(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        bot.common, "get_messages_with_cache", _fake_fetch(captured, monkeypatch)
    )
    await bot.get_history_messages(_ctx(), after=100, count=5)
    assert captured["message_ids"] == [101, 102, 103, 104, 105]


async def test_from_to_inclusive(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        bot.common, "get_messages_with_cache", _fake_fetch(captured, monkeypatch)
    )
    await bot.get_history_messages(_ctx(), from_id=10, to_id=12)
    # inclusive on both ends regardless of count
    assert captured["message_ids"] == [10, 11, 12]


async def test_range_over_limit_rejected(monkeypatch):
    result = await bot.get_history_messages(_ctx(), from_id=1, to_id=300)
    assert "exceeds 200" in result


async def test_mixed_selectors_rejected():
    result = await bot.get_history_messages(_ctx(), before=5, from_id=1, to_id=2)
    assert "exactly one selector" in result


async def test_from_without_to_rejected():
    result = await bot.get_history_messages(_ctx(), from_id=5)
    assert "exactly one selector" in result


async def test_reversed_range_rejected():
    result = await bot.get_history_messages(_ctx(), from_id=10, to_id=5)
    assert "to_id must be >= from_id" in result


async def test_count_out_of_bounds_rejected():
    try:
        await bot.get_history_messages(_ctx(), count=0)
        raise AssertionError("expected ModelRetry")
    except Exception as e:
        assert "between 1 and 200" in str(e)


async def test_reply_chain_selector_rejected_when_combined():
    result = await bot.get_history_messages(_ctx(), reply_chain_of=5, before=4)
    assert "exactly one selector" in result


class _RawMsg:
    def __init__(self, mid: int, reply_to_msg_id: int | None = None):
        self.id = mid
        self.reply_to = (
            SimpleNamespace(reply_to_msg_id=reply_to_msg_id)
            if reply_to_msg_id is not None
            else None
        )


async def test_reply_chain_of_fetches_chain(monkeypatch):
    """reply_chain_of=<id> walks the raw GetMessages reply headers and
    formats the chain oldest-first ending at the anchor."""
    captured: dict = {}
    monkeypatch.setattr(
        bot.common, "get_messages_with_cache", _fake_fetch(captured, monkeypatch)
    )
    # anchor 9 -> 8 -> 7 -> 6; 6 has no further reply
    by_id = {6: _RawMsg(6), 7: _RawMsg(7, 6), 8: _RawMsg(8, 7), 9: _RawMsg(9, 8)}
    invokes: list = []

    async def fake_resolve_peer(chat_id):
        return SimpleNamespace(peer=chat_id)

    async def fake_invoke(query):
        invokes.append(query)
        msgs = []
        for item in query.id:
            mid = getattr(item, "id", None)
            if mid in by_id:
                msgs.append(by_id[mid])
        return SimpleNamespace(messages=msgs)

    ctx = _ctx()
    ctx.deps.client = SimpleNamespace(  # type: ignore[typeddict-item]
        resolve_peer=fake_resolve_peer,
        invoke=fake_invoke,
    )
    result = await bot.get_history_messages(ctx, reply_chain_of=9)
    # ids oldest-first with the anchor last
    assert captured["message_ids"] == [6, 7, 8, 9]
    assert "msg 6" in result and "msg 9" in result


async def test_reply_chain_of_unknown_message(monkeypatch):
    """An anchor Telegram does not know yields an explicit error."""
    invokes: list = []

    async def fake_resolve_peer(chat_id):
        return SimpleNamespace(peer=chat_id)

    async def fake_invoke(query):
        invokes.append(query)
        return SimpleNamespace(messages=[])

    ctx = _ctx()
    ctx.deps.client = SimpleNamespace(  # type: ignore[typeddict-item]
        resolve_peer=fake_resolve_peer,
        invoke=fake_invoke,
    )
    result = await bot.get_history_messages(ctx, reply_chain_of=999)
    assert "message not found" in result
