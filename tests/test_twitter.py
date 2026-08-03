"""Native Twitter/X parsing tests — services layer (pure functions) plus the
plugin wiring with network and Telegram calls stubbed.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from kmua.plugins import twitter as twitter_plugin
from kmua.services import twitter as twitter_service

# FxEmbed v2 style responses
_IMG_TWEET = {
    "code": 200,
    "status": {
        "id": "266031293945503744",
        "text": "Four more years. http://t.co/bAJE6Vom",
        "created_timestamp": 1357868401,
        "media": {
            "all": [
                {
                    "type": "photo",
                    "url": "https://pbs.twimg.com/media/A7E.jpg?name=orig",
                },
                {
                    "type": "photo",
                    "url": "https://pbs.twimg.com/media/A7F.jpg?name=orig",
                },
            ]
        },
        "quote": None,
    },
    "author": {"name": "Barack Obama", "screen_name": "BarackObama"},
}

_VIDEO_TWEET = {
    "code": 200,
    "status": {
        "id": "2082511887757881648",
        "text": "watch this",
        "created_timestamp": 1357868401,
        "media": {
            "all": [
                {
                    "type": "video",
                    "url": "https://video.twimg.com/ext_tw_video/x.mp4",
                }
            ]
        },
        "quote": None,
    },
    "author": {"name": "NASA", "screen_name": "NASA"},
}

_TEXT_TWEET = {
    "code": 200,
    "status": {
        "id": "20",
        "text": "just setting up my twttr",
        "media": {},
        "quote": None,
    },
    "author": {"name": "jack", "screen_name": "jack"},
}

_QUOTE_TWEET = {
    "code": 200,
    "status": {
        "id": "1913228111870566757",
        "text": "check this",
        "media": {},
        "quote": {"text": "the original tweet"},
    },
    "author": {"name": "A", "screen_name": "a"},
}

_TWEET_URL = "https://twitter.com/BarackObama/status/266031293945503744"


# ------------------------------------------------------------------ parsing


def test_extract_tweet_id():
    assert (
        twitter_service.extract_tweet_id("https://twitter.com/foo/status/123456")
        == "123456"
    )
    assert twitter_service.extract_tweet_id("x.com/a/status/99?lang=en") == "99"
    assert twitter_service.extract_tweet_id("https://example.com/status/1") is None


def test_parse_tweet_response_photos():
    tweet = twitter_service.parse_tweet_response(_IMG_TWEET, _TWEET_URL)
    assert tweet is not None
    assert tweet.tweet_id == "266031293945503744"
    assert tweet.author_name == "Barack Obama"
    assert tweet.text.startswith("Four more years")
    assert len(tweet.media) == 2
    assert tweet.media[0].kind == "photo"
    assert tweet.media[0].url.startswith("https://pbs.twimg.com")


def test_parse_tweet_response_video():
    tweet = twitter_service.parse_tweet_response(
        _VIDEO_TWEET, "https://x.com/NASA/status/2082511887757881648"
    )
    assert tweet is not None
    assert tweet.media[0].kind == "video"


def test_parse_tweet_response_pure_text():
    tweet = twitter_service.parse_tweet_response(
        _TEXT_TWEET, "https://twitter.com/jack/status/20"
    )
    assert tweet is not None
    assert tweet.media == []
    assert tweet.text == "just setting up my twttr"


def test_parse_tweet_response_quote():
    tweet = twitter_service.parse_tweet_response(_QUOTE_TWEET, _TWEET_URL)
    assert tweet is not None
    assert tweet.quote_text == "the original tweet"


def test_parse_tweet_response_rejects_missing_status():
    assert twitter_service.parse_tweet_response({"code": 404}, _TWEET_URL) is None
    assert twitter_service.parse_tweet_response({}, _TWEET_URL) is None


def test_build_tweet_text_escapes_and_links():
    tweet = twitter_service.parse_tweet_response(_TEXT_TWEET, _TWEET_URL)
    assert tweet is not None
    html = twitter_service.build_tweet_text(tweet, lang="zh-CN")
    assert "<b>jack</b>" in html
    assert "查看原推" in html
    assert _TWEET_URL in html


def test_build_tweet_text_escapes_html_injection():
    tweet = twitter_service.TweetData(
        url=_TWEET_URL,
        tweet_id="1",
        text="<script>alert(1)</script>",
        author_name="A<b>",
        author_screen_name="a",
    )
    html = twitter_service.build_tweet_text(tweet, lang="zh-CN")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


# ------------------------------------------------------------- plugin wiring


@pytest.fixture
def fake_message():
    import pyrogram

    class FakeReply:
        def __init__(self):
            self.texts = []
            self.media_groups = []

        async def reply_text(self, text, **kwargs):
            self.texts.append((text, kwargs))

        async def reply_chat_action(self, action):
            pass

    chat = pyrogram.types.Chat(
        id=-100_123456789, type=pyrogram.enums.ChatType.SUPERGROUP, title="测试群"
    )
    user = pyrogram.types.User(id=1001, first_name="Tester")
    return chat, user, FakeReply()


def _make_message(fake_message, url):
    import pyrogram

    chat, user, reply = fake_message
    message = pyrogram.types.Message(
        id=1,
        chat=chat,
        from_user=user,
        text=url,
        service=False,
        outgoing=False,
    )
    message.matches = [type("M", (), {"group": lambda self: url})()]
    message.reply_text = reply.reply_text
    message.reply_chat_action = reply.reply_chat_action
    return message


async def test_plugin_sends_text_for_pure_tweet(fake_message, monkeypatch):
    from kmua.database.models import ChatConfig

    async def fake_get_chat_config(chat_id):
        return ChatConfig(parse_artwork_enabled=True)

    monkeypatch.setattr("kmua.database.get_chat_config", fake_get_chat_config)

    tweet = twitter_service.parse_tweet_response(_TEXT_TWEET, _TWEET_URL)
    assert tweet is not None

    async def fake_fetch(url):
        return tweet

    monkeypatch.setattr(twitter_service, "fetch_tweet", fake_fetch)
    message = _make_message(fake_message, "https://twitter.com/jack/status/20")
    await twitter_plugin.parse_tweet(None, message)

    chat, user, reply = fake_message
    assert len(reply.texts) == 1
    text, kwargs = reply.texts[0]
    assert "jack" in text
    assert kwargs["link_preview_options"].is_disabled is False


async def test_plugin_sends_media_group(fake_message, monkeypatch):
    from kmua.database.models import ChatConfig

    async def fake_get_chat_config(chat_id):
        return ChatConfig(parse_artwork_enabled=True)

    monkeypatch.setattr("kmua.database.get_chat_config", fake_get_chat_config)

    tweet = twitter_service.parse_tweet_response(_IMG_TWEET, _TWEET_URL)
    assert tweet is not None

    async def fake_fetch(url):
        return tweet

    async def fake_download(client, media):
        return b"fake-image-bytes"

    media_calls = []

    async def fake_send_media_group(chat_id, media, **kwargs):
        media_calls.append((media, kwargs))

    monkeypatch.setattr(twitter_service, "fetch_tweet", fake_fetch)
    monkeypatch.setattr(twitter_plugin, "_download_media", fake_download)
    fake_client = SimpleNamespace(send_media_group=fake_send_media_group)
    message = _make_message(
        fake_message, "https://twitter.com/BarackObama/status/266031293945503744"
    )
    await twitter_plugin.parse_tweet(fake_client, message)

    assert len(media_calls) == 1
    inputs, kwargs = media_calls[0]
    assert len(inputs) == 2
    assert kwargs.get("show_caption_above_media") is True
    assert inputs[0].caption and "Barack Obama" in inputs[0].caption
    assert inputs[1].caption == ""


async def test_plugin_disabled_by_chat_config(fake_message, monkeypatch):
    from kmua.database.models import ChatConfig

    async def fake_get_chat_config(chat_id):
        return ChatConfig(parse_artwork_enabled=False)

    monkeypatch.setattr("kmua.database.get_chat_config", fake_get_chat_config)

    called = []

    async def fake_fetch(url):
        called.append(url)

    monkeypatch.setattr(twitter_service, "fetch_tweet", fake_fetch)
    message = _make_message(fake_message, "https://twitter.com/jack/status/20")
    await twitter_plugin.parse_tweet(None, message)
    assert called == []


async def test_plugin_silent_when_fetch_fails(fake_message, monkeypatch):
    from kmua.database.models import ChatConfig

    async def fake_get_chat_config(chat_id):
        return ChatConfig(parse_artwork_enabled=True)

    monkeypatch.setattr("kmua.database.get_chat_config", fake_get_chat_config)

    async def fake_fetch(url):
        return None

    monkeypatch.setattr(twitter_service, "fetch_tweet", fake_fetch)
    message = _make_message(fake_message, "https://twitter.com/jack/status/20")
    await twitter_plugin.parse_tweet(None, message)

    chat, user, reply = fake_message
    assert reply.texts == []


async def test_fetch_tweet_caches_by_tweet_id(monkeypatch):
    """Same tweet via x.com and twitter.com shares one API call."""
    import uuid

    from kmua import common

    calls = []

    class FakeResp:
        status_code = 200

        def json(self):
            return _IMG_TWEET

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            calls.append(url)
            return FakeResp()

    monkeypatch.setattr(twitter_service.httpx, "AsyncClient", FakeClient)
    tweet_id = str(uuid.uuid4().int)[:16]
    try:
        first = await twitter_service.fetch_tweet(
            f"https://x.com/foo/status/{tweet_id}"
        )
        second = await twitter_service.fetch_tweet(
            f"https://twitter.com/foo/status/{tweet_id}?s=20"
        )
        assert first is not None and second is not None
        assert first.tweet_id == second.tweet_id == "266031293945503744"
        assert len(calls) == 1
    finally:
        await common.memttlcache.delete(f"twitter:tweet:{tweet_id}")
