"""Channel comment poll normalization contracts."""

from __future__ import annotations

from types import SimpleNamespace

import pyrogram.enums
import pytest

pytestmark = pytest.mark.usefixtures("initialised_db")


@pytest.fixture
async def cc():
    # Imported lazily: the module pulls in the agent graph, which spawns
    # background tasks at import time (needs a running loop).
    from kmua.plugins.agent.channel_comment import (
        CommentResult,
        _normalize_poll,
    )

    return CommentResult, _normalize_poll


async def test_normalize_poll_clamps_to_api_limits(cc):
    _, normalize = cc
    poll = normalize(
        "q" * 300,
        ["a" * 200, "b", "c", "d", "e", "f", "g", "h", "i", "j", "k"],
    )
    assert poll is not None
    question, options = poll
    assert len(question) == 255
    assert len(options) == 10  # Telegram allows at most 10
    assert len(options[0]) == 100


async def test_normalize_poll_skips_empty_and_whitespace_options(cc):
    _, normalize = cc
    # Empty options are filtered; fewer than two survivors drop the poll.
    assert normalize("q", ["a", "", "  "]) is None
    assert normalize("q", ["a", "", "b"]) == ("q", ["a", "b"])


async def test_normalize_poll_requires_two_options_and_question(cc):
    _, normalize = cc
    assert normalize("q", ["a"]) is None
    assert normalize("", ["a", "b"]) is None
    assert normalize("  ", ["a", "b"]) is None


async def test_comment_result_accepts_single_option(cc):
    """The schema must not fail structured output for one option; the send
    gate (>= 2) decides whether a poll is actually posted."""
    CommentResult, normalize = cc
    result = CommentResult(comment="c", poll_question="q", poll_options=["a"])
    assert result.poll_options == ["a"]
    assert normalize(result.poll_question, result.poll_options) is None


async def test_comment_filter_media_follows_struct_model_capability(monkeypatch):
    """Messages with media the comment model cannot take are silently
    skipped; enabling the struct model's multimodal support admits them."""
    from pyrogram.enums import MessageMediaType

    from kmua.plugins.agent import channel_comment as cc

    def embedded(msg):
        return cc._media_would_be_embedded(msg)  # type: ignore[arg-type]

    # Non-text media is embedded as multimodal content.
    assert embedded(
        SimpleNamespace(media=MessageMediaType.PHOTO, photo=SimpleNamespace())
    )
    # Polls, web pages and text documents stay textual.
    assert not embedded(SimpleNamespace(media=MessageMediaType.POLL, poll=None))
    assert not embedded(SimpleNamespace(media=MessageMediaType.WEB_PAGE, web_page=None))
    assert not embedded(SimpleNamespace(media=None))
    assert not embedded(
        SimpleNamespace(
            media=MessageMediaType.DOCUMENT,
            document=SimpleNamespace(
                file_size=100,
                mime_type="text/plain",
                file_name="notes.txt",
            ),
        )
    )
    assert embedded(
        SimpleNamespace(
            media=MessageMediaType.DOCUMENT,
            document=SimpleNamespace(
                file_size=100,
                mime_type="application/pdf",
                file_name="report.pdf",
            ),
        )
    )


async def test_the_comment_run_is_billed_to_the_group(monkeypatch):
    """频道身份没有个人账户, 于是这次模型调用记在群账上 —— 和匿名管理同一条规则。"""
    from contextlib import asynccontextmanager

    from pydantic_ai.usage import RunUsage

    from kmua import database
    from kmua.config import app_config
    from kmua.plugins.agent import channel_comment

    monkeypatch.setattr(app_config, "agent", True, raising=False)
    monkeypatch.setattr(app_config, "agent_group_prompt", "", raising=False)
    monkeypatch.setattr(channel_comment, "is_chat_allowed", lambda _chat_id: True)

    async def first_media(_message):
        return True

    async def no_override(_chat_id):
        return None

    async def input_prompt(*_args, **_kwargs):
        return ["提问"], None, None

    async def reply(*_args, **_kwargs):
        return None

    @asynccontextmanager
    async def typing(_client, _message):
        yield

    class _CommentAgent:
        async def run(self, **_kwargs):
            return SimpleNamespace(
                output=channel_comment.CommentResult(comment="说两句"),
                usage=RunUsage(input_tokens=900, output_tokens=100),
            )

    monkeypatch.setattr(channel_comment, "_is_first_media_in_group", first_media)
    monkeypatch.setattr(channel_comment, "get_chat_prompt_override", no_override)
    monkeypatch.setattr(channel_comment, "get_input_prompt", input_prompt)
    monkeypatch.setattr(channel_comment, "TypingKeepAlive", typing)
    monkeypatch.setattr(channel_comment, "reply_output", reply)
    monkeypatch.setattr(channel_comment, "comment_agent", _CommentAgent())

    message = SimpleNamespace(
        chat=SimpleNamespace(id=-1009400001, type=pyrogram.enums.ChatType.SUPERGROUP),
        sender_chat=SimpleNamespace(
            id=-1009400002, title="频道", bio=None, description=None
        ),
        from_user=None,
        id=555,
        caption="看看这个",
        text=None,
        reply_text=None,
    )

    day = database.utc_day()
    before = await database.get_usage(database.SCOPE_CHAT, message.chat.id, day)
    await channel_comment.comment_channel_message(SimpleNamespace(), message)
    after = await database.get_usage(database.SCOPE_CHAT, message.chat.id, day)

    assert after[0] == before[0] + 1
    assert (after[2] - before[2], after[3] - before[3]) == (900, 100)
    assert (await database.get_usage(database.SCOPE_USER, -1009400002, day))[0] == 0
