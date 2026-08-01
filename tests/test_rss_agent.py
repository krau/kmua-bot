"""RSS × Agent: digest summary and broadcast tests.

Covers the pure prompt/parse functions in ``kmua.plugins.agent.rss_digest``,
the failure fallbacks (agent output must never drop a push), and the
``jobs.rss_push`` integration with per-chat switches, rate limiting and
``parse_mode=None`` broadcasts. All model calls are stubbed — no network.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from kmua import common, database
from kmua.bot import jobs
from kmua.config import app_config
from kmua.database.models import ChatConfig
from kmua.plugins.agent import rss_digest
from kmua.services.rss import FeedEntry, FetchResult

pytestmark = pytest.mark.usefixtures("initialised_db")

CHAT_ID = -100_910_002


@pytest.fixture(autouse=True)
def agent_gate(monkeypatch):
    """Pass the agent gate so generate_* actually call the (stubbed) agent."""
    monkeypatch.setattr(app_config, "agent", True, raising=False)
    monkeypatch.setattr(app_config, "agent_model", "unvapp/kmua", raising=False)
    # Reset the lazily-built agent singletons between tests so a stubbed agent
    # from one test is not reused by the next.
    monkeypatch.setattr(rss_digest, "_digest_agent", None)
    monkeypatch.setattr(rss_digest, "_broadcast_agent", None)


def make_entry(
    entry_id: str, title: str = "标题", link: str = "https://example.com/x"
) -> FeedEntry:
    return FeedEntry(entry_id=entry_id, title=title, link=link, summary="摘要内容")


def make_feed() -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        url="https://example.com/feed.xml",
        etag=None,
        last_modified=None,
        # A past fetch time so rss_push reaches the delivery branch (a None
        # last_fetched_at triggers the first-fetch seed path that pushes nothing).
        last_fetched_at=datetime.now(UTC) - timedelta(minutes=60),
        seen_entry_ids=[],
        failure_count=0,
    )


def make_fetch_result() -> FetchResult:
    return FetchResult(
        not_modified=False,
        feed_title="测试 Feed",
        etag=None,
        last_modified=None,
        entries=[
            make_entry("e1", title="第一条"),
            make_entry("e2", title="第二条"),
        ],
    )


# ---------------------------------------------------------------- pure fns


def test_build_digest_prompt_contains_entries_and_title():
    entries = [make_entry("e1"), make_entry("e2")]
    prompt = rss_digest.build_digest_prompt(entries, "测试 Feed")
    assert "[e1]" in prompt and "[e2]" in prompt
    assert "测试 Feed" in prompt
    assert "https://example.com/x" in prompt


def test_build_digest_prompt_uses_chat_language():
    prompt = rss_digest.build_digest_prompt([make_entry("e1")], "F", lang="en")
    assert "用 en 语言" in prompt


def test_parse_digest_output_filters_valid_ids():
    payload = (
        '{"summaries": ['
        '{"entry_id": "e1", "summary": "点评一"},'
        '{"entry_id": "e2", "summary": "点评二"},'
        '{"entry_id": "e3", "summary": "点评三"}'
        "]}"
    )
    out = rss_digest.parse_digest_output(payload, {"e1", "e2"})
    assert out == {"e1": "点评一", "e2": "点评二"}


def test_parse_digest_output_accepts_instance():
    article = rss_digest.RssDigestSummaries(
        summaries=[
            rss_digest.RssEntrySummary(entry_id="e1", summary="点评一"),
        ]
    )
    out = rss_digest.parse_digest_output(article, {"e1", "e2"})
    assert out == {"e1": "点评一"}


def test_parse_digest_output_rejects_garbage():
    assert rss_digest.parse_digest_output("not json", {"e1"}) == {}
    assert rss_digest.parse_digest_output("", {"e1"}) == {}
    assert rss_digest.parse_digest_output('["list"]', {"e1"}) == {}
    assert rss_digest.parse_digest_output('{"e1": 42}', {"e1"}) == {}
    assert (
        rss_digest.parse_digest_output(
            '{"summaries": [{"entry_id": "e1", "summary": 42}]}', {"e1"}
        )
        == {}
    )


def test_build_broadcast_prompt_contains_titles_and_links():
    prompt = rss_digest.build_broadcast_prompt([make_entry("e1")], "测试 Feed")
    assert "标题" in prompt
    assert "https://example.com/x" in prompt


# --------------------------------------------------------- failure fallback


class _FakeAgent:
    def __init__(self, result):
        self._result = result
        self.calls = 0

    async def run(self, **kwargs):
        self.calls += 1
        if isinstance(self._result, Exception):
            raise self._result
        return SimpleNamespace(output=self._result)


@pytest.mark.parametrize("raise_exc", [RuntimeError("boom"), TimeoutError("t/o")])
async def test_generate_digest_returns_empty_on_failure(monkeypatch, raise_exc):
    fake = _FakeAgent(raise_exc)
    monkeypatch.setattr(rss_digest, "_make_digest_agent", lambda: fake)
    out = await rss_digest.generate_rss_digest([make_entry("e1")], "feed")
    assert out == {}


async def test_generate_digest_parses_agent_output(monkeypatch):
    fake = _FakeAgent('{"summaries": [{"entry_id": "e1", "summary": "点评"}]}')
    monkeypatch.setattr(rss_digest, "_make_digest_agent", lambda: fake)
    out = await rss_digest.generate_rss_digest([make_entry("e1")], "feed")
    assert out == {"e1": "点评"}


async def test_generate_broadcast_returns_none_on_failure(monkeypatch):
    fake = _FakeAgent(RuntimeError("boom"))
    monkeypatch.setattr(rss_digest, "_make_broadcast_agent", lambda: fake)
    out = await rss_digest.generate_rss_broadcast([make_entry("e1")], "feed")
    assert out is None


async def test_generate_broadcast_strips_blank_output(monkeypatch):
    fake = _FakeAgent("   ")
    monkeypatch.setattr(rss_digest, "_make_broadcast_agent", lambda: fake)
    out = await rss_digest.generate_rss_broadcast([make_entry("e1")], "feed")
    assert out is None


# ------------------------------------------------------------- jobs wiring


@pytest.fixture
def rss_agent_env(monkeypatch):
    """Enable agent gating, stub the database and the Telegram client."""
    monkeypatch.setattr(app_config, "rss_agent_broadcast_interval", 30, raising=False)

    sent: list[tuple[int, str | None, str]] = []  # (chat_id, text, parse_mode)

    async def fake_send_message(chat_id, text, parse_mode=None, **kwargs):
        sent.append((chat_id, text, parse_mode))
        return SimpleNamespace(id=1)

    async def fake_get_chat(chat_id):
        return SimpleNamespace(type=__import__("pyrogram").enums.ChatType.SUPERGROUP)

    fake_client = SimpleNamespace(
        send_message=fake_send_message, get_chat=fake_get_chat
    )

    async def fake_chat_lang(chat_id):
        return "zh-CN"

    monkeypatch.setattr(jobs, "_chat_lang", fake_chat_lang, raising=False)

    async def fake_active_feeds():
        return [(make_feed(), 30)]

    monkeypatch.setattr(database, "get_active_feeds", fake_active_feeds)

    async def fake_get_feed_target_chats(feed_id):
        return [CHAT_ID]

    monkeypatch.setattr(database, "get_feed_target_chats", fake_get_feed_target_chats)
    monkeypatch.setattr(
        # kmua/bot/__init__.py re-exports the client instance, so the package
        # attribute "kmua.bot.client" is the Client, not the module; import the
        # submodule explicitly to patch the real attribute.
        importlib.import_module("kmua.bot.client"),
        "client",
        fake_client,
        raising=False,
    )

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(database, "record_fetch_success", noop, raising=False)
    monkeypatch.setattr(database, "touch_fetch", noop, raising=False)

    return sent


@pytest.fixture
def stub_fetch(monkeypatch):
    async def fake_fetch(url, **kwargs):
        return make_fetch_result()

    # jobs.rss_push fetches via `kmua.services.rss.fetch_feed` (imported inside
    # the job), so patching the module attribute covers it.
    monkeypatch.setattr("kmua.services.rss.fetch_feed", fake_fetch, raising=False)


async def test_push_with_summary_prepends_digest(
    monkeypatch, rss_agent_env, stub_fetch, initialised_db
):
    cfg = ChatConfig(rss_agent_summary=True)

    async def fake_get_chat_config(chat_id):
        return cfg

    monkeypatch.setattr(database, "get_chat_config", fake_get_chat_config)

    async def fake_digest(entries, feed_title, lang):
        return {"e1": "点评一"}

    monkeypatch.setattr(rss_digest, "generate_rss_digest", fake_digest)
    await jobs.rss_push()

    sent = rss_agent_env
    assert sent, "no message was sent"
    # e1 got the digest prefix; e2 (no digest) still pushed raw.
    texts = [text for _, text, _ in sent]
    assert any(text.startswith("💬 点评一") for text in texts)
    assert any("第二条" in text for text in texts)


async def test_push_without_digest_keeps_raw_text(
    monkeypatch, rss_agent_env, stub_fetch, initialised_db
):
    async def fake_get_chat_config(chat_id):
        return ChatConfig()

    monkeypatch.setattr(database, "get_chat_config", fake_get_chat_config)
    await jobs.rss_push()

    texts = [text for _, text, _ in rss_agent_env]
    assert texts and all(not text.startswith("💬") for text in texts)
    assert any("第一条" in text for text in texts)


async def test_broadcast_sent_with_plain_text_and_rate_limited(
    monkeypatch, rss_agent_env, stub_fetch, initialised_db
):
    await common.memttlcache.delete(f"rss:broadcast:{CHAT_ID}")
    cfg = ChatConfig(rss_agent_broadcast=True)

    async def fake_get_chat_config(chat_id):
        return cfg

    monkeypatch.setattr(database, "get_chat_config", fake_get_chat_config)

    calls = []

    async def fake_broadcast(entries, feed_title, lang):
        calls.append(lang)
        return "播报文本"

    monkeypatch.setattr(rss_digest, "generate_rss_broadcast", fake_broadcast)

    await jobs.rss_push()
    broadcasts = [
        (chat_id, text, mode)
        for chat_id, text, mode in rss_agent_env
        if text == "播报文本"
    ]
    assert len(broadcasts) == 1
    chat_id, text, mode = broadcasts[0]
    assert chat_id == CHAT_ID
    assert mode is None  # parse_mode=None, plain text

    # Second poll: the rate-limit lock is held, so generation is skipped
    # entirely (no extra LLM call) and nothing new is broadcast.
    await jobs.rss_push()
    assert len(calls) == 1
    broadcasts = [
        (chat_id, text, mode)
        for chat_id, text, mode in rss_agent_env
        if text == "播报文本"
    ]
    assert len(broadcasts) == 1


async def test_all_switches_off_matches_plain_push(
    monkeypatch, rss_agent_env, stub_fetch, initialised_db
):
    async def fake_get_chat_config(chat_id):
        return ChatConfig()

    monkeypatch.setattr(database, "get_chat_config", fake_get_chat_config)
    await jobs.rss_push()
    texts = [text for _, text, _ in rss_agent_env]
    assert len(texts) == 2  # two entries, no extra broadcast


async def test_rss_agent_toggle_requires_chat_row(
    initialised_db,
):
    """A private chat has no ChatData row: the toggle must reply a hint,
    not crash, and the switch must not be persisted anywhere."""
    import pyrogram

    from kmua.plugins.rss import _rss_agent_toggle

    chat_id = 9_000_123
    chat = pyrogram.types.Chat(
        id=chat_id, type=pyrogram.enums.ChatType.PRIVATE, title=None
    )
    replies: list[str] = []

    async def reply(text, **kwargs):
        replies.append(text)

    message = SimpleNamespace(chat=chat, reply=reply)
    await _rss_agent_toggle(
        message, "zh-CN", ["rss", "digest", "on"], "rss_agent_summary"
    )

    assert replies and "无法保存" in replies[0]


async def test_rss_agent_toggle_persists_for_group_chat(
    initialised_db,
):
    """A group chat with a ChatData row toggles on and off and persists."""
    import pyrogram

    from kmua.plugins.rss import _rss_agent_toggle

    chat_id = -100_9_000_123
    chat = pyrogram.types.Chat(
        id=chat_id, type=pyrogram.enums.ChatType.SUPERGROUP, title="测试群"
    )
    replies: list[str] = []

    async def reply(text, **kwargs):
        replies.append(text)

    message = SimpleNamespace(chat=chat, reply=reply)
    await _rss_agent_toggle(
        message, "zh-CN", ["rss", "digest", "on"], "rss_agent_summary"
    )

    cfg = await database.get_chat_config(chat_id)
    assert cfg.rss_agent_summary is True
    assert cfg.rss_agent_broadcast is False
    assert replies and "已开启" in replies[0]

    # Toggling back off persists too.
    await _rss_agent_toggle(
        message, "zh-CN", ["rss", "digest", "off"], "rss_agent_summary"
    )
    cfg = await database.get_chat_config(chat_id)
    assert cfg.rss_agent_summary is False
    assert replies[-1] and "已关闭" in replies[-1]
