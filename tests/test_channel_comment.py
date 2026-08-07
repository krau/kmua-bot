"""Channel comment poll normalization contracts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


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
