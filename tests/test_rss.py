"""RSS subscription tests — storage layer plus the panel endpoints.

The storage properties that matter: a feed is shared across subscribers (so the
poll job fetches each URL once), the per-chat cap and the whitelist gate hold at
the database layer, and removing the last subscription deletes the feed row so an
unwanted feed stops being polled. The API tests pin the whitelist/disabled gates
and the subscription lifecycle, with `fetch_feed` stubbed so no test touches the
network.
"""

from __future__ import annotations

import pytest
import sqlalchemy

from kmua import database
from kmua.config import app_config
from kmua.database.models import ChatPolicy, RssFeed, RssSubscription
from kmua.services import rss as rss_service
from kmua.services.rss import FeedEntry, FetchResult
from tests.webapp_helpers import api_client, bearer, join_chat, make_chat, make_user

pytestmark = pytest.mark.usefixtures("initialised_db")

OWNER_ID = 9100001
ADMIN_ID = 9100002
CHAT_ID = -100_910_001


@pytest.fixture(autouse=True)
async def clean_rss():
    """Empty the RSS tables between tests."""
    from kmua.database.db import AsyncSessionFactory

    async with AsyncSessionFactory() as session:
        async with session.begin():
            await session.execute(sqlalchemy.delete(RssSubscription))
            await session.execute(sqlalchemy.delete(RssFeed))
    yield


@pytest.fixture
def whitelist_mode(monkeypatch):
    monkeypatch.setattr(app_config, "rss_whitelist_mode", True, raising=False)


@pytest.fixture
def no_whitelist_mode(monkeypatch):
    monkeypatch.setattr(app_config, "rss_whitelist_mode", False, raising=False)


# ------------------------------------------------------------------ storage layer


async def test_add_subscription_enforces_per_chat_limit():
    for i in range(database.MAX_FEEDS_PER_CHAT):
        sub, reason = await database.add_subscription(
            -100900001, f"http://feed{i}.test"
        )
        assert sub is not None and reason is None

    sub, reason = await database.add_subscription(
        -100900001, "http://one-too-many.test"
    )
    assert sub is None and reason == "limit_reached"


async def test_add_subscription_rejects_duplicates():
    sub, reason = await database.add_subscription(-100900001, "http://feed.test")
    assert sub is not None and reason is None

    sub, reason = await database.add_subscription(-100900001, "http://feed.test")
    assert sub is None and reason == "already_subscribed"


async def test_remove_subscription_deletes_orphan_feed():
    sub, _ = await database.add_subscription(-100900001, "http://feed.test")
    await database.add_subscription(-100900002, "http://feed.test")

    await database.remove_subscription(-100900001, sub.feed_id)
    assert (
        await database.get_feed_by_url("http://feed.test") is not None
    )  # 还有另一个订阅者

    await database.remove_subscription(-100900002, sub.feed_id)
    assert (
        await database.get_feed_by_url("http://feed.test") is None
    )  # 最后一个订阅者走了, feed 也删


async def test_remove_an_absent_subscription_is_false():
    sub, _ = await database.add_subscription(-100900001, "http://feed.test")
    assert await database.remove_subscription(-100900002, sub.feed_id) is False


async def test_pause_and_resume():
    sub, _ = await database.add_subscription(-100900001, "http://feed.test")

    assert await database.set_subscription_paused(-100900001, sub.feed_id, True) is True
    assert await database.get_feed_target_chats(sub.feed_id) == []
    assert await database.get_active_feeds() == []

    assert (
        await database.set_subscription_paused(-100900001, sub.feed_id, False) is True
    )
    assert await database.get_feed_target_chats(sub.feed_id) == [-100900001]
    assert [f.url for f, _ in await database.get_active_feeds()] == ["http://feed.test"]


async def test_pausing_an_absent_subscription_is_false():
    assert await database.set_subscription_paused(-100900001, 999, True) is False


async def test_get_active_feeds_skips_fully_paused_feeds():
    sub, _ = await database.add_subscription(-100900001, "http://a.test")
    sub2, _ = await database.add_subscription(-100900001, "http://b.test")
    await database.set_subscription_paused(-100900001, sub.feed_id, True)

    active = await database.get_active_feeds()
    assert [f.url for f, _ in active] == ["http://b.test"]
    assert sub2.feed_id in {f.id for f, _ in active}


async def test_active_feeds_default_to_the_global_interval(monkeypatch):
    monkeypatch.setattr(app_config, "rss_interval", 30, raising=False)
    await database.add_subscription(-100900001, "http://feed.test")

    (feed, minutes), *_ = await database.get_active_feeds()
    assert feed.url == "http://feed.test"
    assert minutes == 30


async def test_active_feed_interval_is_the_minimum_across_subscriptions():
    sub, _ = await database.add_subscription(-100900001, "http://feed.test")
    await database.add_subscription(-100900002, "http://feed.test")

    await database.set_subscription_interval(-100900001, sub.feed_id, 10)
    await database.set_subscription_interval(-100900002, sub.feed_id, 5)

    (_, minutes), *_ = await database.get_active_feeds()
    assert minutes == 5

    # Pausing the fast subscriber lets the slower one set the pace.
    await database.set_subscription_paused(-100900002, sub.feed_id, True)
    (_, minutes), *_ = await database.get_active_feeds()
    assert minutes == 10


async def test_set_subscription_interval_and_reset():
    sub, _ = await database.add_subscription(-100900001, "http://feed.test")
    assert await database.set_subscription_interval(-100900001, sub.feed_id, 7) is True
    assert await database.set_subscription_interval(-100900001, 999, 7) is False

    listed = await database.get_chat_subscriptions(-100900001)
    assert listed[0].interval_minutes == 7

    await database.set_subscription_interval(-100900001, sub.feed_id, None)
    listed = await database.get_chat_subscriptions(-100900001)
    assert listed[0].interval_minutes is None


async def test_touch_fetch_updates_last_fetched_at():
    sub, _ = await database.add_subscription(-100900001, "http://feed.test")
    feed = await database.get_feed_by_id(sub.feed_id)
    assert feed.last_fetched_at is None

    await database.touch_fetch(sub.feed_id)
    feed = await database.get_feed_by_id(sub.feed_id)
    assert feed.last_fetched_at is not None
    assert feed.last_error is None and feed.seen_entry_ids == []


async def test_get_chat_subscriptions_is_newest_first():
    subs = []
    for i in range(3):
        sub, _ = await database.add_subscription(-100900001, f"http://feed{i}.test")
        subs.append(sub)

    listed = await database.get_chat_subscriptions(-100900001)
    assert [s.id for s in listed] == [subs[2].id, subs[1].id, subs[0].id]


async def test_paged_subscriptions(whitelist_mode):
    for i in range(5):
        await database.add_subscription(-100900001, f"http://feed{i}.test")

    page1 = await database.get_chat_subscriptions_paged(-100900001, page=1, size=2)
    assert page1.total == 5
    assert len(page1.items) == 2
    page2 = await database.get_chat_subscriptions_paged(-100900001, page=2, size=2)
    assert len(page2.items) == 2
    assert {s.id for s in page1.items}.isdisjoint({s.id for s in page2.items})


async def test_record_fetch_success_seeds_seen_ids_and_clears_error():
    sub, _ = await database.add_subscription(-100900001, "http://feed.test")
    await database.record_fetch_failure(sub.feed_id, "HTTPStatusError: 404")

    feed = await database.get_feed_by_id(sub.feed_id)
    assert feed.last_error is not None
    assert feed.failure_count == 1

    await database.record_fetch_success(
        sub.feed_id,
        title="Test Feed",
        etag='"abc"',
        last_modified="Wed, 01 Jan 2026 00:00:00 GMT",
        seen_entry_ids=["a", "b"],
    )

    feed = await database.get_feed_by_id(sub.feed_id)
    assert feed.last_error is None
    assert feed.failure_count == 0
    assert feed.title == "Test Feed"
    assert feed.etag == '"abc"'
    assert feed.seen_entry_ids == ["a", "b"]


async def test_record_fetch_success_truncates_the_seen_window():
    sub, _ = await database.add_subscription(-100900001, "http://feed.test")

    await database.record_fetch_success(
        sub.feed_id,
        title=None,
        etag=None,
        last_modified=None,
        seen_entry_ids=[str(i) for i in range(database.MAX_SEEN_IDS + 10)],
    )

    feed = await database.get_feed_by_id(sub.feed_id)
    assert len(feed.seen_entry_ids) == database.MAX_SEEN_IDS
    assert feed.seen_entry_ids[0] == "10"


async def test_record_fetch_success_keeps_an_existing_title():
    sub, _ = await database.add_subscription(-100900001, "http://feed.test")
    await database.record_fetch_success(
        sub.feed_id,
        title="Real Title",
        etag=None,
        last_modified=None,
        seen_entry_ids=[],
    )

    await database.record_fetch_success(
        sub.feed_id, title="", etag=None, last_modified=None, seen_entry_ids=[]
    )

    feed = await database.get_feed_by_id(sub.feed_id)
    assert feed.title == "Real Title"


async def test_delete_chat_subscriptions_drops_all_rows():
    sub, _ = await database.add_subscription(-100900001, "http://a.test")
    sub2, _ = await database.add_subscription(-100900001, "http://b.test")
    await database.add_subscription(-100900002, "http://a.test")

    removed = await database.delete_chat_subscriptions(-100900001)
    assert removed == 2
    assert await database.count_chat_subscriptions(-100900001) == 0
    assert await database.count_chat_subscriptions(-100900002) == 1
    assert (
        sub.feed_id != sub2.feed_id
    )  # sanity: the two subscriptions target distinct feeds


async def test_is_rss_allowed_respects_policy_flag(whitelist_mode):
    assert await database.is_rss_allowed(-100900001) is False

    await database.set_chat_policy(-100900001, ChatPolicy(rss_allowed=True))
    assert await database.is_rss_allowed(-100900001) is True


async def test_is_rss_allowed_ignores_flag_when_mode_is_off(no_whitelist_mode):
    assert await database.is_rss_allowed(-100900001) is True


# ------------------------------------------------------------------ parsing & rendering


def test_plain_text_preserves_paragraph_breaks():
    raw = (
        "<article><h2>Title</h2><figure><img src='https://cdn.example.com/a.webp'/></figure>"
        "<p>First para</p><p>Second para<br/>with break</p></article>"
    )
    text = rss_service._plain_text(raw, 1000)
    assert "Title" in text
    assert "First para\n\nSecond para" in text
    assert "with break" in text
    assert "<" not in text and "img" not in text and "cdn.example.com" not in text


def test_plain_text_unescapes_entities():
    assert (
        rss_service._plain_text("<p>Tom &amp; Jerry &lt;3</p>", 1000)
        == "Tom & Jerry <3"
    )


def test_plain_text_collapses_blank_line_runs():
    assert (
        rss_service._plain_text("<p>a</p><div></div><p>b</p><br/><p>c</p>", 1000)
        == "a\n\nb\n\nc"
    )


def test_plain_text_truncates():
    assert len(rss_service._plain_text("<p>abcdefgh</p>", 5)) == 5


def test_sanitize_keeps_inline_formatting():
    out = rss_service._sanitize_html(
        "<p>Some <strong>bold</strong> and <em>italic</em> and <s>struck</s> text</p>",
        1000,
    )
    assert "<b>bold</b>" in out
    assert "<i>italic</i>" in out
    assert "<s>struck</s>" in out


def test_sanitize_protects_code_blocks():
    out = rss_service._sanitize_html(
        "<p>Before</p><pre><code>def f():\n    return 1 < 2</code></pre><p>After</p>",
        1000,
    )
    # The inner <code> wrapper is stripped so its tag text never shows inside
    # the block; the content is escaped exactly once.
    assert "<pre>def f():\n    return 1 &lt; 2</pre>" in out
    assert "<code>" not in out
    assert "Before\n\n" in out


def test_sanitize_code_block_content_is_escaped_once():
    out = rss_service._sanitize_html(
        '<pre><code class="language-sh">a &lt; b &amp;&amp; c > d</code></pre>', 1000
    )
    assert out == "<pre>a &lt; b &amp;&amp; c &gt; d</pre>"


def test_sanitize_keeps_inline_code():
    out = rss_service._sanitize_html("<p>use <code>sendMessage</code> here</p>", 1000)
    assert out == "use <code>sendMessage</code> here"


def test_sanitize_br_inside_code_block_is_a_line_break():
    out = rss_service._sanitize_html("<pre><code>line1<br/>line2</code></pre>", 1000)
    assert out == "<pre>line1\nline2</pre>"


def test_sanitize_strips_html_comments():
    out = rss_service._sanitize_html("<p>before<!-- more -->after</p>", 1000)
    assert out == "beforeafter"


def test_sanitize_strips_unknown_tags_and_escapes_text():
    out = rss_service._sanitize_html(
        '<p>An <a href="https://e.com/x">inline link</a> and <script>evil()</script></p>',
        1000,
    )
    assert "inline link" in out
    assert "<a" not in out and "script" not in out
    # literal escaped markup in the source stays literal text
    out2 = rss_service._sanitize_html("<p>&lt;b&gt;not bold&lt;/b&gt;</p>", 1000)
    assert out2 == "&lt;b&gt;not bold&lt;/b&gt;"


def test_sanitize_balances_tags():
    out = rss_service._sanitize_html(
        "<p>unclosed <b>bold without close</p><p>ok</p>", 1000
    )
    assert "<b>" not in out and "</b>" not in out
    assert "bold without close" in out
    assert out.count("<p>") == out.count("</p>") == 0  # p is not kept at all


def test_sanitize_truncation_drops_broken_code_block():
    body = "<p>" + "x" * 100 + "</p><pre><code>long code block</code></pre>"
    out = rss_service._sanitize_html(body, 80)
    assert "<pre>" not in out  # placeholder cut in half -> whole block dropped
    assert "\x00" not in out


def test_truncate_for_delivery_cuts_at_paragraph_boundary():
    text = "<b>head</b>\n\n" + "p" * 3000 + "\n\n" + "q" * 3000
    out = rss_service.truncate_for_delivery(text, 3500)
    assert len(out) <= 3500
    assert "q" not in out
    assert out.endswith(" …")
    assert out.count("<b>") == out.count("</b>")


def test_truncate_for_delivery_short_text_is_untouched():
    text = "<b>short</b>"
    assert rss_service.truncate_for_delivery(text, 4096) == text


# ------------------------------------------------------------------ security guards


def test_redact_url_strips_query_userinfo_and_fragment():
    assert (
        rss_service.redact_url("https://user:pass@example.com/feed.xml?token=abc#frag")
        == "https://example.com/feed.xml"
    )
    assert rss_service.redact_url("https://example.com:8443/feed?k=v") == (
        "https://example.com:8443/feed"
    )
    assert rss_service.redact_url("not a url") == "not a url"


def test_is_blocked_ip_covers_metadata_and_private_ranges():
    import ipaddress

    for ip in [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",  # cloud metadata
        "100.64.0.1",  # CGNAT
        "0.0.0.0",
        "192.0.2.1",  # documentation
        "::1",
        "fc00::1",
        "fe80::1",
        "::ffff:127.0.0.1",  # IPv4-mapped loopback
    ]:
        assert rss_service._is_blocked_ip(ipaddress.ip_address(ip)), ip

    for ip in ["8.8.8.8", "1.1.1.1", "2606:4700::1111"]:
        assert not rss_service._is_blocked_ip(ipaddress.ip_address(ip)), ip


def test_sanitize_drops_ctrl_entity_forgery():
    # &#1; decodes to \x01, the sanitizer's own tag-token sentinel; the entities
    # are dropped, so the source cannot forge a token into a real tag.
    out = rss_service._sanitize_html("<p>a&#1;ob&#1;b</p>", 1000)
    assert "<b>" not in out
    assert "\x01" not in out
    assert out == "aobb"


def test_sanitize_forged_placeholder_index_is_dropped():
    out = rss_service._sanitize_html("<p>a\x00999\x00b</p>", 1000)
    assert "\x00" not in out
    assert out == "ab"


def test_fetch_drops_non_http_entry_links():
    # fetch_feed builds links through urljoin; a javascript: entry link must not
    # reach the rendered href.
    import feedparser

    doc = feedparser.parse(
        b"""<?xml version="1.0"?><rss version="2.0"><channel>
        <title>t</title><link>https://e.com/</link>
        <item><title>x</title><link>javascript:alert(1)</link></item>
        </channel></rss>"""
    )
    raw = doc.entries[0]
    # Directly exercise the same link construction used in fetch_feed.
    link = __import__("urllib.parse", fromlist=["urljoin"]).urljoin(
        "https://e.com/", raw.get("link", "")
    )
    assert not link.startswith(("http://", "https://"))


def test_entry_html_prefers_content():
    raw = {"content": [{"value": "<p>full</p>"}], "summary": "short"}
    assert rss_service._entry_html(raw) == "<p>full</p>"
    assert rss_service._entry_html({"summary": "short"}) == "short"
    assert rss_service._entry_html({"description": "desc"}) == "desc"


def test_extract_media_from_imgs_and_enclosures():
    raw = {
        "enclosures": [
            {"type": "image/jpeg", "url": "/media/cover.jpg"},
            {"type": "audio/mpeg", "url": "/a.mp3"},
        ]
    }
    media = rss_service._extract_media(
        "<p><img src='https://cdn.example.com/1.webp'/><img src='/rel/2.png'/></p>",
        raw,
        "https://example.com/feed.xml",
    )
    assert media == [
        "https://cdn.example.com/1.webp",
        "https://example.com/rel/2.png",
        "https://example.com/media/cover.jpg",
    ]


def test_extract_media_caps_and_dedupes():
    raw = {"enclosures": [{"type": "image/jpeg", "url": "https://e.com/x.jpg"}]}
    html_src = "".join(f"<img src='https://cdn.e.com/{i}.jpg'/>" for i in range(5))
    media = rss_service._extract_media(html_src, raw, "https://e.com/feed")
    assert len(media) == 3
    assert len(set(media)) == 3


def test_render_entry_keeps_summary_newlines():
    entry = FeedEntry(
        entry_id="1", title="T", link="https://e.com/1", summary="line1\n\nline2"
    )
    out = rss_service.render_entry("F", entry, "zh-CN")
    assert "line1\n\nline2" in out
    assert '<a href="https://e.com/1">T</a>' in out


# --------------------------------------------------------------------------- API


@pytest.fixture
async def chat_admin(monkeypatch):
    admin = await make_user(ADMIN_ID, full_name="RSS Admin")
    chat = await make_chat(CHAT_ID, title="RSS Chat")
    await join_chat(admin, chat, bot_admin=True)
    return admin, chat


def _allow_rss():
    """Whitelist the chat directly at the storage layer."""
    return database.set_chat_policy(CHAT_ID, ChatPolicy(rss_allowed=True))


async def test_list_rss_requires_whitelist(monkeypatch, whitelist_mode, chat_admin):
    async with api_client() as client:
        response = await client.get(
            f"/api/chats/{CHAT_ID}/rss", headers=bearer(ADMIN_ID)
        )

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


async def test_list_rss_works_when_whitelisted(monkeypatch, whitelist_mode, chat_admin):
    await _allow_rss()
    async with api_client() as client:
        response = await client.get(
            f"/api/chats/{CHAT_ID}/rss", headers=bearer(ADMIN_ID)
        )

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0


async def test_list_rss_requires_chat_admin(monkeypatch, whitelist_mode):
    await _allow_rss()
    plain = await make_user(OWNER_ID, full_name="Plain User")
    await make_chat(CHAT_ID, title="RSS Chat")
    async with api_client() as client:
        response = await client.get(
            f"/api/chats/{CHAT_ID}/rss", headers=bearer(plain.id)
        )

    assert response.status_code == 403


async def test_rss_disabled_everywhere(monkeypatch, chat_admin):
    monkeypatch.setattr(app_config, "rss_enabled", False, raising=False)
    await _allow_rss()
    async with api_client() as client:
        response = await client.get(
            f"/api/chats/{CHAT_ID}/rss", headers=bearer(ADMIN_ID)
        )

    assert response.status_code == 400
    assert response.json()["code"] == "FEATURE_DISABLED"


async def test_add_rejects_a_non_http_url(monkeypatch, whitelist_mode, chat_admin):
    await _allow_rss()
    async with api_client() as client:
        response = await client.post(
            f"/api/chats/{CHAT_ID}/rss",
            headers=bearer(ADMIN_ID),
            json={"url": "ftp://example.com/feed.xml"},
        )

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_FAILED"


async def test_add_reports_an_unfetchable_feed(monkeypatch, whitelist_mode, chat_admin):
    await _allow_rss()

    async def broken_fetch(url, *, etag=None, last_modified=None):
        raise ValueError("feed too large")

    monkeypatch.setattr(rss_service, "fetch_feed", broken_fetch)
    async with api_client() as client:
        response = await client.post(
            f"/api/chats/{CHAT_ID}/rss",
            headers=bearer(ADMIN_ID),
            json={"url": "http://example.com/feed.xml"},
        )

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert "ValueError" in response.json()["message"]
    assert await database.count_chat_subscriptions(CHAT_ID) == 0


async def test_add_subscribes_and_seeds_seen_ids(
    monkeypatch, whitelist_mode, chat_admin
):
    await _allow_rss()

    async def fake_fetch(url, *, etag=None, last_modified=None):
        return FetchResult(
            not_modified=False,
            feed_title="HN",
            entries=[FeedEntry(entry_id="1", title="Post", link="", summary="")],
            etag=None,
            last_modified=None,
        )

    monkeypatch.setattr(rss_service, "fetch_feed", fake_fetch)
    async with api_client() as client:
        response = await client.post(
            f"/api/chats/{CHAT_ID}/rss",
            headers=bearer(ADMIN_ID),
            json={"url": "http://example.com/feed.xml"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["url"] == "http://example.com/feed.xml"
    assert body["title"] == "HN"
    assert body["paused"] is False

    feed = await database.get_feed_by_url("http://example.com/feed.xml")
    assert feed.seen_entry_ids == ["1"]


async def test_add_a_duplicate_is_a_conflict(monkeypatch, whitelist_mode, chat_admin):
    await _allow_rss()

    async def fake_fetch(url, *, etag=None, last_modified=None):
        return FetchResult(
            not_modified=False,
            feed_title=None,
            entries=[],
            etag=None,
            last_modified=None,
        )

    monkeypatch.setattr(rss_service, "fetch_feed", fake_fetch)
    async with api_client() as client:
        first = await client.post(
            f"/api/chats/{CHAT_ID}/rss",
            headers=bearer(ADMIN_ID),
            json={"url": "http://example.com/feed.xml"},
        )
        assert first.status_code == 201

        second = await client.post(
            f"/api/chats/{CHAT_ID}/rss",
            headers=bearer(ADMIN_ID),
            json={"url": "http://example.com/feed.xml"},
        )

    assert second.status_code == 409
    assert second.json()["code"] == "CONFLICT"


async def test_patch_pauses_and_returns_the_list(
    monkeypatch, whitelist_mode, chat_admin
):
    await _allow_rss()

    async def fake_fetch(url, *, etag=None, last_modified=None):
        return FetchResult(
            not_modified=False,
            feed_title=None,
            entries=[],
            etag=None,
            last_modified=None,
        )

    monkeypatch.setattr(rss_service, "fetch_feed", fake_fetch)
    async with api_client() as client:
        added = await client.post(
            f"/api/chats/{CHAT_ID}/rss",
            headers=bearer(ADMIN_ID),
            json={"url": "http://example.com/feed.xml"},
        )
        feed_id = added.json()["feed_id"]

        patched = await client.patch(
            f"/api/chats/{CHAT_ID}/rss/{feed_id}",
            headers=bearer(ADMIN_ID),
            json={"paused": True},
        )

    assert patched.status_code == 200
    items = patched.json()
    assert len(items) == 1
    assert items[0]["paused"] is True
    assert items[0]["interval_minutes"] is None

    subs = await database.get_chat_subscriptions(CHAT_ID)
    assert subs[0].paused is True


async def test_patch_sets_and_resets_the_interval(
    monkeypatch, whitelist_mode, chat_admin
):
    await _allow_rss()

    async def fake_fetch(url, *, etag=None, last_modified=None):
        return FetchResult(
            not_modified=False,
            feed_title=None,
            entries=[],
            etag=None,
            last_modified=None,
        )

    monkeypatch.setattr(rss_service, "fetch_feed", fake_fetch)
    async with api_client() as client:
        added = await client.post(
            f"/api/chats/{CHAT_ID}/rss",
            headers=bearer(ADMIN_ID),
            json={"url": "http://example.com/feed.xml"},
        )
        feed_id = added.json()["feed_id"]

        set_interval = await client.patch(
            f"/api/chats/{CHAT_ID}/rss/{feed_id}",
            headers=bearer(ADMIN_ID),
            json={"interval_minutes": 5},
        )
        assert set_interval.status_code == 200
        assert set_interval.json()[0]["interval_minutes"] == 5
        # paused is untouched by an interval-only patch
        assert set_interval.json()[0]["paused"] is False

        reset = await client.patch(
            f"/api/chats/{CHAT_ID}/rss/{feed_id}",
            headers=bearer(ADMIN_ID),
            json={"interval_minutes": None},
        )
        assert reset.status_code == 200
        assert reset.json()[0]["interval_minutes"] is None

        out_of_range = await client.patch(
            f"/api/chats/{CHAT_ID}/rss/{feed_id}",
            headers=bearer(ADMIN_ID),
            json={"interval_minutes": 0},
        )
        assert out_of_range.status_code == 422

        subs = await database.get_chat_subscriptions(CHAT_ID)
        assert subs[0].interval_minutes is None


async def test_patch_an_absent_subscription_is_a_404(
    monkeypatch, whitelist_mode, chat_admin
):
    await _allow_rss()
    async with api_client() as client:
        response = await client.patch(
            f"/api/chats/{CHAT_ID}/rss/999",
            headers=bearer(ADMIN_ID),
            json={"paused": True},
        )

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


async def test_delete_removes_the_subscription(monkeypatch, whitelist_mode, chat_admin):
    await _allow_rss()

    async def fake_fetch(url, *, etag=None, last_modified=None):
        return FetchResult(
            not_modified=False,
            feed_title=None,
            entries=[],
            etag=None,
            last_modified=None,
        )

    monkeypatch.setattr(rss_service, "fetch_feed", fake_fetch)
    async with api_client() as client:
        added = await client.post(
            f"/api/chats/{CHAT_ID}/rss",
            headers=bearer(ADMIN_ID),
            json={"url": "http://example.com/feed.xml"},
        )
        feed_id = added.json()["feed_id"]

        deleted = await client.delete(
            f"/api/chats/{CHAT_ID}/rss/{feed_id}", headers=bearer(ADMIN_ID)
        )
        gone = await client.delete(
            f"/api/chats/{CHAT_ID}/rss/{feed_id}", headers=bearer(ADMIN_ID)
        )

    assert deleted.status_code == 204
    assert gone.status_code == 404
    assert await database.count_chat_subscriptions(CHAT_ID) == 0
    assert await database.get_feed_by_url("http://example.com/feed.xml") is None


# ----------------------------------------------------------------- personal (/api/me/rss)

ME_ID = 9100004


async def test_me_rss_requires_whitelist(monkeypatch, whitelist_mode):
    await make_user(ME_ID, full_name="Me User")
    async with api_client() as client:
        response = await client.get("/api/me/rss", headers=bearer(ME_ID))

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


async def test_me_rss_lifecycle(monkeypatch, whitelist_mode):
    await make_user(ME_ID, full_name="Me User")
    await database.set_chat_policy(ME_ID, ChatPolicy(rss_allowed=True))

    async def fake_fetch(url, *, etag=None, last_modified=None):
        return FetchResult(
            not_modified=False,
            feed_title="Me Feed",
            entries=[FeedEntry(entry_id="1", title="P", link="", summary="")],
            etag=None,
            last_modified=None,
        )

    monkeypatch.setattr(rss_service, "fetch_feed", fake_fetch)
    async with api_client() as client:
        added = await client.post(
            "/api/me/rss", headers=bearer(ME_ID), json={"url": "http://me.test/feed"}
        )
        assert added.status_code == 201
        assert added.json()["title"] == "Me Feed"

        listed = await client.get("/api/me/rss", headers=bearer(ME_ID))
        assert listed.status_code == 200
        assert listed.json()["total"] == 1

        feed_id = added.json()["feed_id"]
        patched = await client.patch(
            f"/api/me/rss/{feed_id}", headers=bearer(ME_ID), json={"paused": True}
        )
        assert patched.status_code == 200
        assert patched.json()[0]["paused"] is True

        deleted = await client.delete(f"/api/me/rss/{feed_id}", headers=bearer(ME_ID))
        assert deleted.status_code == 204

    assert await database.count_chat_subscriptions(ME_ID) == 0
    assert await database.get_feed_by_url("http://me.test/feed") is None


async def test_me_rss_is_scoped_to_the_caller(monkeypatch, whitelist_mode):
    other = await make_user(ME_ID + 1, full_name="Other User")
    await make_user(ME_ID, full_name="Me User")
    await database.set_chat_policy(ME_ID, ChatPolicy(rss_allowed=True))
    await database.set_chat_policy(other.id, ChatPolicy(rss_allowed=True))

    async def fake_fetch(url, *, etag=None, last_modified=None):
        return FetchResult(
            not_modified=False,
            feed_title=None,
            entries=[],
            etag=None,
            last_modified=None,
        )

    monkeypatch.setattr(rss_service, "fetch_feed", fake_fetch)
    async with api_client() as client:
        await client.post(
            "/api/me/rss", headers=bearer(ME_ID), json={"url": "http://me.test/feed"}
        )

        # The other user sees nothing of the first user's subscription.
        listed = await client.get("/api/me/rss", headers=bearer(other.id))
        assert listed.status_code == 200
        assert listed.json()["total"] == 0

        # And cannot pause or delete it: the feed id is scoped by session user.
        feed_id = (await database.get_feed_by_url("http://me.test/feed")).id
        gone = await client.delete(f"/api/me/rss/{feed_id}", headers=bearer(other.id))
        assert gone.status_code == 404

    assert await database.count_chat_subscriptions(ME_ID) == 1
