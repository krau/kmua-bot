"""Social link parsing tests — services layer (pure functions + fake HTTP)
and the plugin wiring with network/Telegram calls stubbed.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from kmua.services import link_parse

_COOLAPK_HTML = """
<html><body><div class="feed">
  <div class="message-title">酷安帖子标题</div>
  <div class="feed-article-message">
    <p>酷安正文第一句。</p><p>酷安正文第二句。</p>
    <img class="message-image" src="//qpic.cn/a.jpg">
    <img class="message-image" src="//qpic.cn/b.jpg">
  </div>
</div></body></html>
"""

_COOLAPK_FEED_HTML = """
<html><body><div class="feed">
  <div class="feed-message">没有标题的动态内容</div>
  <div class="message-image-group"><img src="//qpic.cn/c.jpg"></div>
</div></body></html>
"""

_TIEBA_RESPONSE = {
    "error_code": "0",
    "thread": {
        "origin_thread_info": {
            "title": "贴吧帖子标题",
            "content": [
                {"type": 0, "text": "第一行正文"},
                {"type": 0, "text": "第二行正文"},
                {"type": 1, "text": "忽略的图片描述"},
            ],
            "media": [
                {
                    "big_pic": "https://tbpic.cn/1.jpg",
                    "small_pic": "https://tbpic.cn/1s.jpg",
                },
                {"big_pic": "https://tbpic.cn/2.jpg"},
            ],
        },
        "video_info": {},
    },
}

_TIEBA_VIDEO_RESPONSE = {
    "error_code": "0",
    "thread": {
        "origin_thread_info": {
            "title": "视频帖",
            "content": [{"type": 0, "text": "视频正文"}],
            "media": None,
        },
        "video_info": {
            "video_url": "https://vd.bdstatic.com/v.mp4",
            "thumbnail_url": "https://tbpic.cn/thumb.jpg",
        },
    },
}

_TBS_RESPONSE = {"tbs": "fake-tbs-token"}


class _FakeClient:
    """httpx.AsyncClient stand-in: scripted responses per URL, counts calls."""

    def __init__(self, routes):
        self.routes = routes  # {url: (status, payload)}
        self.calls: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def _respond(self, url):
        self.calls.append(url)
        status, payload = self.routes[url]
        return SimpleNamespace(
            status_code=status,
            raise_for_status=lambda: None,
            json=lambda: payload,
            text=payload if isinstance(payload, str) else "",
        )

    async def get(self, url, **kw):
        return await self._respond(url)

    async def post(self, url, **kw):
        return await self._respond(url)


# ------------------------------------------------------------------ matching


def test_match_social_url_detects_each_source():
    assert link_parse.match_social_url(
        "看这个 https://www.coolapk.com/feed/123?shareKey=abc"
    ) == ("coolapk", "https://www.coolapk.com/feed/123?shareKey=abc")
    assert link_parse.match_social_url(
        "帖子 https://tieba.baidu.com/p/7654321 来了"
    ) == ("tieba", "https://tieba.baidu.com/p/7654321")


def test_match_social_url_strips_trailing_punctuation():
    assert link_parse.match_social_url("https://tieba.baidu.com/p/7654321。")[
        1
    ].endswith("7654321")


def test_match_social_url_rejects_unknown():
    assert link_parse.match_social_url("https://example.com/feed/1") is None
    assert link_parse.match_social_url("tieba.baidu.com/p/abc") is None


# ------------------------------------------------------------- fetch + parse


async def test_fetch_coolapk_article(monkeypatch):
    url = "https://www.coolapk.com/feed/123?shareKey=abc"
    fake = _FakeClient({url: (200, _COOLAPK_HTML)})
    monkeypatch.setattr(link_parse.httpx, "AsyncClient", lambda **kw: fake)
    post = await link_parse.fetch_social_post(url)
    assert post is not None
    assert post.source == "coolapk"
    assert post.title == "酷安帖子标题"
    assert "酷安正文第一句" in post.text
    assert post.images == ["https://qpic.cn/a.jpg", "https://qpic.cn/b.jpg"]
    assert fake.calls == [url]


async def test_fetch_coolapk_feed_only(monkeypatch):
    url = "https://www.coolapk.com/picture/456?shareKey=abc"
    fake = _FakeClient({url: (200, _COOLAPK_FEED_HTML)})
    monkeypatch.setattr(link_parse.httpx, "AsyncClient", lambda **kw: fake)
    post = await link_parse.fetch_social_post(url)
    assert post is not None
    assert post.title == ""
    assert post.text == "没有标题的动态内容"
    assert post.images == ["https://qpic.cn/c.jpg"]


async def test_fetch_tieba_text_and_photos(monkeypatch):
    url = "https://tieba.baidu.com/p/7654321"
    fake = _FakeClient(
        {
            "http://tieba.baidu.com/dc/common/tbs": (200, _TBS_RESPONSE),
            "https://tieba.baidu.com/c/f/pb/page_pc": (200, _TIEBA_RESPONSE),
        }
    )
    monkeypatch.setattr(link_parse.httpx, "AsyncClient", lambda **kw: fake)
    post = await link_parse.fetch_social_post(url)
    assert post is not None
    assert post.source == "tieba"
    assert post.title == "贴吧帖子标题"
    assert post.text == "第一行正文\n第二行正文"
    assert post.images == [
        "https://tbpic.cn/1.jpg",
        "https://tbpic.cn/2.jpg",
    ]
    assert post.video_url is None
    assert len(fake.calls) == 2


async def test_fetch_tieba_video(monkeypatch):
    url = "https://tieba.baidu.com/p/8888"
    fake = _FakeClient(
        {
            "http://tieba.baidu.com/dc/common/tbs": (200, _TBS_RESPONSE),
            "https://tieba.baidu.com/c/f/pb/page_pc": (200, _TIEBA_VIDEO_RESPONSE),
        }
    )
    monkeypatch.setattr(link_parse.httpx, "AsyncClient", lambda **kw: fake)
    post = await link_parse.fetch_social_post(url)
    assert post is not None
    assert post.video_url == "https://vd.bdstatic.com/v.mp4"
    assert post.images == []


async def test_fetch_social_post_caches_per_url(monkeypatch):
    from kmua import common

    url = "https://tieba.baidu.com/p/42424242"
    fake = _FakeClient(
        {
            "http://tieba.baidu.com/dc/common/tbs": (200, _TBS_RESPONSE),
            "https://tieba.baidu.com/c/f/pb/page_pc": (200, _TIEBA_RESPONSE),
        }
    )
    monkeypatch.setattr(link_parse.httpx, "AsyncClient", lambda **kw: fake)
    try:
        first = await link_parse.fetch_social_post(url)
        second = await link_parse.fetch_social_post(url)
        assert first is not None and second is not None
        assert first.title == second.title
        assert len(fake.calls) == 2  # tbs + page_pc, once
    finally:
        await common.memttlcache.delete(f"social:tieba:{url}")


async def test_fetch_social_post_failure_returns_none(monkeypatch):
    url = "https://tieba.baidu.com/p/1"
    fake = _FakeClient(
        {
            "http://tieba.baidu.com/dc/common/tbs": (200, {"tbs": "t"}),
            "https://tieba.baidu.com/c/f/pb/page_pc": (200, {"error_code": "4"}),
        }
    )
    monkeypatch.setattr(link_parse.httpx, "AsyncClient", lambda **kw: fake)
    assert await link_parse.fetch_social_post(url) is None


async def test_fetch_social_post_rejects_unsupported():
    assert await link_parse.fetch_social_post("https://example.com/feed/1") is None


# ------------------------------------------------------------- plugin wiring


@pytest.fixture
def fake_message():
    import pyrogram

    chat = SimpleNamespace(id=-100123, type=pyrogram.enums.ChatType.SUPERGROUP)
    user = SimpleNamespace(id=1001)
    reply = SimpleNamespace(texts=[], chat_actions=[], id=5)

    async def fake_reply(text=None, parse_mode=None, link_preview_options=None):
        reply.texts.append(text)
        return SimpleNamespace()

    message = SimpleNamespace(
        chat=chat,
        from_user=user,
        sender_chat=None,
        id=1,
        text=None,
        matches=None,
        reply_text=fake_reply,
        reply_chat_action=lambda *a, **kw: asyncio.sleep(0),
    )
    return chat, user, reply, message


async def test_plugin_gated_by_parse_sites_enabled(fake_message, monkeypatch):
    from kmua.database.models import ChatConfig
    from kmua.plugins import link_parse as plugin

    chat, user, reply, message = fake_message
    message.text = "https://tieba.baidu.com/p/123456"
    message.matches = [SimpleNamespace(group=lambda: message.text)]

    async def fake_get_chat_config(chat_id):
        return ChatConfig(
            parse_sites_enabled={"tieba": False},
        )

    async def fake_fetch(url):
        raise AssertionError("should not parse when disabled")

    monkeypatch.setattr("kmua.database.get_chat_config", fake_get_chat_config)
    monkeypatch.setattr(link_parse, "fetch_social_post", fake_fetch)
    await plugin.parse_social_link(None, message)
    assert reply.texts == []


async def test_plugin_sends_text_without_images(fake_message, monkeypatch):
    from kmua.database.models import ChatConfig
    from kmua.plugins import link_parse as plugin

    chat, user, reply, message = fake_message
    message.text = "https://tieba.baidu.com/p/123456"
    message.matches = [SimpleNamespace(group=lambda: message.text)]

    async def fake_get_chat_config(chat_id):
        return ChatConfig(parse_sites_enabled={})

    post = link_parse.SocialPost(
        source="tieba",
        url="https://tieba.baidu.com/p/123456",
        title="标题",
        text="正文内容",
    )

    async def fake_fetch(url):
        return post

    async def fake_download(urls):
        return []

    monkeypatch.setattr("kmua.database.get_chat_config", fake_get_chat_config)
    monkeypatch.setattr(link_parse, "fetch_social_post", fake_fetch)
    monkeypatch.setattr(plugin, "_download_images", fake_download)
    await plugin.parse_social_link(None, message)
    assert reply.texts and "标题" in reply.texts[0]
    assert "正文内容" in reply.texts[0]
    assert "查看原文" in reply.texts[0]


async def test_plugin_sends_media_group(fake_message, monkeypatch):
    import pyrogram

    from kmua.database.models import ChatConfig
    from kmua.plugins import link_parse as plugin

    chat, user, reply, message = fake_message
    message.text = "https://www.coolapk.com/feed/7?shareKey=abc"
    message.matches = [SimpleNamespace(group=lambda: message.text)]
    sent = []

    async def fake_send_media_group(chat_id, inputs, **kw):
        sent.append(inputs)
        return []

    async def fake_get_chat_config(chat_id):
        return ChatConfig(parse_sites_enabled={})

    post = link_parse.SocialPost(
        source="coolapk",
        url="https://www.coolapk.com/feed/7?shareKey=abc",
        title="酷安",
        text="正文",
        images=["https://qpic.cn/a.jpg"],
    )

    async def fake_fetch(url):
        return post

    async def fake_download(urls):
        return [b"\xff\xd8\xffbinary"]

    monkeypatch.setattr("kmua.database.get_chat_config", fake_get_chat_config)
    monkeypatch.setattr(link_parse, "fetch_social_post", fake_fetch)
    monkeypatch.setattr(plugin, "_download_images", fake_download)
    client = SimpleNamespace(send_media_group=fake_send_media_group)
    await plugin.parse_social_link(client, message)
    assert len(sent) == 1
    assert len(sent[0]) == 1
    assert isinstance(sent[0][0], pyrogram.types.InputMediaPhoto)
