"""Per-site link-parsing switches (parse_sites_enabled in ChatConfig).

Covers the site-key helper in manyacg and the gating in the manyacg and
twitter parsers.
"""

from __future__ import annotations

import pyrogram
import pytest

from kmua.plugins import twitter as twitter_plugin
from kmua.plugins.manyacg import manyacg as manyacg_plugin
from kmua.services import manyacg as manyacg_service
from kmua.services import twitter as twitter_service


class _FakeReply:
    def __init__(self):
        self.texts = []
        self.media_groups = []
        self.actions = []

    async def reply_text(self, text, **kwargs):
        self.texts.append(text)

    async def reply_chat_action(self, action):
        self.actions.append(action)


def _make_message(url):
    chat = pyrogram.types.Chat(
        id=-100_111, type=pyrogram.enums.ChatType.SUPERGROUP, title="测试群"
    )
    user = pyrogram.types.User(id=1001, first_name="Tester")
    message = pyrogram.types.Message(
        id=1, chat=chat, from_user=user, text=url, service=False, outgoing=False
    )
    message.matches = [type("M", (), {"group": lambda self: url})()]
    reply = _FakeReply()
    message.reply_text = reply.reply_text
    message.reply_chat_action = reply.reply_chat_action
    return message, reply


def test_match_artwork_site():
    assert (
        manyacg_service.match_artwork_site("https://pixiv.net/artworks/123") == "pixiv"
    )
    assert (
        manyacg_service.match_artwork_site(
            "https://www.pixiv.net/en/artworks/128546841"
        )
        == "pixiv"
    )
    assert (
        manyacg_service.match_artwork_site("https://www.pixiv.net/zh-cn/artworks/1")
        == "pixiv"
    )
    assert (
        manyacg_service.match_artwork_site("https://t.bilibili.com/123") == "bilibili"
    )
    assert (
        manyacg_service.match_artwork_site("https://danbooru.donmai.us/posts/1")
        == "danbooru"
    )
    assert manyacg_service.match_artwork_site("https://nhentai.net/g/1") == "nhentai"
    assert manyacg_service.match_artwork_site("https://twitter.com/a/status/1") is None
    assert manyacg_service.match_artwork_site("https://example.com/1") is None
    assert len(manyacg_service.ARTWORK_SITES) == len(manyacg_service.ARTWORK_ALL_REGEX)


def test_pixiv_regex_bounded_on_pathological_input():
    """A long member_illust query tail with no illust_id must scan fast.

    The pre-illust_id parameter skip is bounded; unbounded it backtracked
    quadratically over the whole message text on every incoming message.
    """
    import time

    from kmua.services.manyacg import PIXIV_REGEX

    assert PIXIV_REGEX.search("pixiv.net/member_illust.php?mode=medium&illust_id=42")
    evil = "pixiv.net/member_illust.php?" + "a=" * 3000
    start = time.perf_counter()
    assert PIXIV_REGEX.search(evil) is None
    assert time.perf_counter() - start < 0.05


@pytest.fixture
def chat_config_factory(monkeypatch):
    from kmua.database.models import ChatConfig

    def install(sites: dict[str, bool]):
        async def fake_get_chat_config(chat_id):
            return ChatConfig(
                parse_artwork_enabled=True,
                parse_sites_enabled=sites,
            )

        monkeypatch.setattr("kmua.database.get_chat_config", fake_get_chat_config)
        monkeypatch.setattr(
            "kmua.plugins.twitter.database.get_chat_config", fake_get_chat_config
        )
        monkeypatch.setattr(
            "kmua.plugins.manyacg.manyacg.database.get_chat_config",
            fake_get_chat_config,
        )

    return install


async def test_twitter_skipped_when_site_off(chat_config_factory, monkeypatch):
    chat_config_factory({"twitter": False})
    fetched = []

    async def fake_fetch(url):
        fetched.append(url)
        return None

    monkeypatch.setattr(twitter_service, "fetch_tweet", fake_fetch)
    message, reply = _make_message("https://twitter.com/jack/status/20")
    await twitter_plugin.parse_tweet(None, message)
    assert fetched == []
    assert reply.texts == []


async def test_twitter_runs_when_other_sites_off(chat_config_factory, monkeypatch):
    chat_config_factory({"pixiv": False, "bilibili": False})
    tweet = twitter_service.TweetData(
        url="https://twitter.com/jack/status/20",
        tweet_id="20",
        text="just setting up my twttr",
        author_name="jack",
        author_screen_name="jack",
    )
    fetched = []

    async def fake_fetch(url):
        fetched.append(url)
        return tweet

    monkeypatch.setattr(twitter_service, "fetch_tweet", fake_fetch)
    message, reply = _make_message("https://twitter.com/jack/status/20")
    await twitter_plugin.parse_tweet(None, message)
    assert len(fetched) == 1
    assert len(reply.texts) == 1


async def test_manyacg_skipped_when_site_off(chat_config_factory, monkeypatch):
    chat_config_factory({"pixiv": False})
    monkeypatch.setattr("kmua.config.app_config.manyacg_api_key", "fake-key")
    calls = []

    async def fake_fetch(url):
        calls.append(url)
        return manyacg_service.FetchArtworkResponse(status=200, message="ok", data=None)

    monkeypatch.setattr(manyacg_plugin.manyacg_client, "fetch_artwork", fake_fetch)
    message, reply = _make_message("https://pixiv.net/artworks/123")
    await manyacg_plugin.parse_artwork(None, message)
    assert calls == []
    assert reply.texts == []


async def test_manyacg_runs_when_other_sites_off(chat_config_factory, monkeypatch):
    chat_config_factory({"twitter": False})
    monkeypatch.setattr("kmua.config.app_config.manyacg_api_key", "fake-key")
    calls = []

    async def fake_fetch(url):
        calls.append(url)
        return manyacg_service.FetchArtworkResponse(
            status=200,
            message="ok",
            data=manyacg_service.FetchedArtwork(
                title="x",
                description="",
                tags=[],
                source_url=url,
                artist=None,
                source_type="pixiv",
                r18=False,
            ),
        )

    monkeypatch.setattr(manyacg_plugin.manyacg_client, "fetch_artwork", fake_fetch)
    message, reply = _make_message("https://danbooru.donmai.us/posts/1")
    await manyacg_plugin.parse_artwork(None, message)
    assert calls == ["https://danbooru.donmai.us/posts/1"]


async def test_manyacg_runs_with_locale_pixiv_url(chat_config_factory, monkeypatch):
    chat_config_factory({"twitter": False})
    monkeypatch.setattr("kmua.config.app_config.manyacg_api_key", "fake-key")
    calls = []

    async def fake_fetch(url):
        calls.append(url)
        return manyacg_service.FetchArtworkResponse(
            status=200,
            message="ok",
            data=manyacg_service.FetchedArtwork(
                title="x",
                description="",
                tags=[],
                source_url=url,
                artist=None,
                source_type="pixiv",
                r18=False,
            ),
        )

    monkeypatch.setattr(manyacg_plugin.manyacg_client, "fetch_artwork", fake_fetch)
    message, reply = _make_message("https://www.pixiv.net/en/artworks/128546841")
    await manyacg_plugin.parse_artwork(None, message)
    assert calls == ["https://www.pixiv.net/en/artworks/128546841"]
