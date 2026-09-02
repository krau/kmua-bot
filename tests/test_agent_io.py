"""Unified agent IO tools (protocol prefixes: kmua://, ws://, http(s)://)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest
from pydantic_ai import RunContext, RunUsage
from pydantic_ai.models.test import TestModel
from pyrogram.client import Client
from pyrogram.types import Message

from kmua.config import app_config
from kmua.plugins.agent import datatype
from kmua.plugins.agent.tools import code_repo, io, workspace


@pytest.fixture
async def ws(monkeypatch, tmp_path):
    from agentfs_sdk import AgentFS, AgentFSOptions

    agents: dict[str, AgentFS] = {}

    async def _fake_get(session_key):
        if session_key not in agents:
            agents[session_key] = await AgentFS.open(
                AgentFSOptions(
                    id=f"kmua-test-ws-{session_key}",
                    path=str(tmp_path / f"ws-{session_key}.db"),
                )
            )
        return agents[session_key]

    monkeypatch.setattr(workspace, "get_workspace_agentfs", _fake_get)
    # Session -100123 owns hello.html and demo.py; -100999 owns secret.html.
    agent_a = await _fake_get("-100123")
    await agent_a.fs.write_file("/hello.html", "<h1>hi</h1>\n")
    await agent_a.fs.write_file("/demo.py", "line1\nline2\nline3\n")
    agent_b = await _fake_get("-100999")
    await agent_b.fs.write_file("/secret.html", "other session\n")
    yield agent_a
    for agent in agents.values():
        await agent.close()


def _ctx(client=None, guest=False) -> RunContext[datatype.ContextDeps]:
    return cast(
        RunContext[datatype.ContextDeps],
        SimpleNamespace(
            deps=SimpleNamespace(
                client=client,
                chat_id=-100_123,
                user_id=1001,
                message=SimpleNamespace(id=7, guest_query_id=1 if guest else None),
                is_guest_mode=guest,
                powermemory=SimpleNamespace(),
            )
        ),
    )


def test_split_target():
    assert io._split_target("kmua:///kmua/plugins/x.py") == (
        "kmua://",
        "/kmua/plugins/x.py",
    )
    assert io._split_target("work://notes/a.txt") == ("work://", "/notes/a.txt")
    assert io._split_target("https://x.com/a") == ("http", "https://x.com/a")
    assert io._split_target("http://x.com") == ("http", "http://x.com")
    with pytest.raises(ValueError):
        io._split_target("file:///etc/passwd")


async def test_write_creates_and_reads(ws):
    result = await io.write(_ctx(), "work://notes.txt", "hi there")
    assert "Wrote" in result
    content = await io.read(_ctx(), "work://notes.txt")
    assert "hi there" in content


async def test_write_overwrites_existing(ws):
    await io.write(_ctx(), "work://hello.html", "v2")
    content = await io.read(_ctx(), "work://hello.html")
    assert "v2" in content
    assert "hi" not in content


async def test_write_rejects_codebase(ws):
    result = await io.write(_ctx(), "kmua://kmua/x.py", "x")
    assert "read-only" in result
    assert "not writable" in result


async def test_write_rejects_path_escape(ws):
    result = await io.write(_ctx(), "work:///a/../secret.txt", "x")
    assert "escapes" in result


async def test_edit_unique_match(ws):
    result = await io.edit(_ctx(), "work://demo.py", "line2", "LINE2")
    assert "Edited" in result
    content = await io.read(_ctx(), "work://demo.py")
    assert "LINE2" in content
    assert "line2" not in content


async def test_edit_ambiguous_match_fails(ws):
    result = await io.edit(_ctx(), "work://demo.py", "line", "X")
    assert "matches 3 times" in result
    content = await io.read(_ctx(), "work://demo.py")
    assert "line1" in content  # unchanged


async def test_edit_missing_text_fails(ws):
    result = await io.edit(_ctx(), "work://demo.py", "nope", "X")
    assert "not found" in result


async def test_read_kmua_protocol(ws, monkeypatch, tmp_path):
    from agentfs_sdk import AgentFS, AgentFSOptions

    code_agent = await AgentFS.open(
        AgentFSOptions(id="kmua-test-code", path=str(tmp_path / "code.db"))
    )
    await code_agent.fs.write_file("/kmua/config/__init__.py", "lineA\nlineB\n")

    async def _fake_code_get():
        return code_agent

    monkeypatch.setattr(code_repo, "get_code_agentfs", _fake_code_get)
    try:
        content = await io.read(
            _ctx(), "kmua:///kmua/config/__init__.py", start_line=1, max_lines=5
        )
        assert "lineA" in content
        assert "lineB" in content
    finally:
        await code_agent.close()
        (tmp_path / "code.db").unlink(missing_ok=True)


async def test_list_workspace(ws):
    result = await io.list(_ctx(), "work://")
    assert "hello.html" in result
    assert "demo.py" in result


async def test_search_workspace(ws):
    result = await io.search(_ctx(), "line", "work://")
    assert "demo.py" in result


async def test_workspace_disabled(ws, monkeypatch):
    monkeypatch.setattr(app_config, "agent_workspace_enabled", False)
    result = await io.write(_ctx(), "work://x.txt", "y")
    assert "disabled" in result


async def test_web_read_disabled(ws, monkeypatch):
    monkeypatch.setattr(app_config, "agent_extra_tools", ["websearch"])
    result = await io.read(_ctx(), "https://example.com")
    assert "disabled" in result


async def test_write_requires_content_for_work(ws):
    result = await io.write(_ctx(), "work://x.txt")
    assert "content is required" in result


# ------------------------------------------------------------ chat:// memory:// web://


def _chat_info():
    return io.db.ChatInfo(
        chat_id=-100_123,
        title="测试群",
        username="testgroup",
        members_count=42,
    )


async def test_read_chat_info(ws, monkeypatch):
    async def fake_get_chat_info(ctx):
        return _chat_info()

    monkeypatch.setattr(io.db, "get_chat_info", fake_get_chat_info)
    result = await io.read(_ctx(), "chat://info")
    assert "测试群" in result
    assert "-100_123" in result or "-100123" in result


async def test_read_chat_history(ws, monkeypatch):
    calls = {}

    async def fake_history(ctx, **kwargs):
        calls.update(kwargs)
        return "history text"

    monkeypatch.setattr(io.bot, "get_history_messages", fake_history)
    result = await io.read(
        _ctx(), "chat://history?direction=before&anchor_id=7&count=30"
    )
    assert result == "history text"
    assert calls["direction"] == "before"
    assert calls["anchor_id"] == 7
    assert calls["count"] == 30


async def test_read_chat_rejected_in_private(ws, monkeypatch):
    ctx = _ctx()
    ctx.deps.chat_id = ctx.deps.user_id  # private chat
    result = await io.read(ctx, "chat://info")
    assert "only available in group chats" in result


async def test_write_memory(ws, monkeypatch):
    calls = []

    async def fake_update(ctx, content):
        calls.append(content)
        return "Memory stored."

    monkeypatch.setattr(io.chat, "update_group_memory", fake_update)
    result = await io.write(_ctx(), "memory://", content="小明喜欢猫")
    assert result == "Memory stored."
    assert calls == ["小明喜欢猫"]


async def test_write_memory_requires_content(ws):
    result = await io.write(_ctx(), "memory://")
    assert "content is required" in result


async def test_write_chat_rejected(ws):
    result = await io.write(_ctx(), "chat://quote", content="老婆")
    assert "read-only" in result or "not writable" in result


async def test_search_web(ws, monkeypatch):
    async def fake_web(query, max_results):
        return "web results for " + query

    monkeypatch.setattr(io, "_search_web", fake_web)
    result = await io.search(_ctx(), "kmua", "web://")
    assert result == "web results for kmua"


async def test_search_web_disabled(ws, monkeypatch):
    monkeypatch.setattr(app_config, "agent_extra_tools", [])
    result = await io.search(_ctx(), "kmua", "web://")
    assert "disabled" in result


async def test_search_memory(ws, monkeypatch):
    async def fake_memory(ctx, query):
        return ["记忆1", "记忆2"]

    monkeypatch.setattr(io.chat, "search_group_memory", fake_memory)
    result = await io.search(_ctx(), "爱好", "memory://")
    assert "记忆1" in result
    assert "记忆2" in result


async def test_search_chat(ws, monkeypatch):
    async def fake_search(ctx, query, count):
        return f"chat results: {query} x{count}"

    monkeypatch.setattr(io.bot, "search_messages", fake_search)
    result = await io.search(_ctx(), "waifu", "chat://")
    assert result == "chat results: waifu x20"


async def test_workspace_session_isolation(ws):
    # Session A (chat -100123, the default _ctx) can see its own files...
    assert "hello.html" in await io.list(_ctx(), "work://")
    # ...but not session B's (chat -100999): separate database.
    ctx_b = _ctx()
    ctx_b.deps.chat_id = -100999
    assert "hello.html" not in await io.list(ctx_b, "work://")
    assert "File not found" in await io.read(ctx_b, "work://hello.html")
    # Session B's file is invisible to session A.
    assert "File not found" in await io.read(_ctx(), "work://secret.html")
    # Search is scoped per session too.
    assert "No results" in await io.search(_ctx(), "secret", "work://")


async def test_write_work_copy_from_reference(ws):
    result = await io.write(_ctx(), "work://copy.py", content="work://demo.py")
    assert "Wrote" in result
    copied = await io.read(_ctx(), "work://copy.py")
    assert "line2" in copied


async def test_write_reference_not_readable(ws):
    # telegram:// is no longer a protocol: the string is treated as plain text
    result = await io.write(_ctx(), "work://x.txt", content="telegram://y.txt")
    assert "Wrote" in result
    content = await io.read(_ctx(), "work://x.txt")
    assert "telegram://y.txt" in content


async def test_workspace_lru_eviction_closes(monkeypatch, tmp_path):
    """Evicting a session closes its connection; re-open creates a fresh one."""
    from agentfs_sdk import AgentFS

    opened: list[AgentFS] = []
    closed: list[AgentFS] = []

    real_open = AgentFS.open

    async def fake_open(options):
        agent = await real_open(options)
        opened.append(agent)
        real_close = agent.close

        async def tracking_close():
            await real_close()
            closed.append(agent)

        agent.close = tracking_close  # type: ignore[method-assign]
        return agent

    monkeypatch.setattr(AgentFS, "open", fake_open)
    monkeypatch.setattr(workspace, "_SESSION_CACHE_MAX", 2)
    monkeypatch.setattr(workspace, "WORKSPACE_AGENTFS_DIR", tmp_path)

    try:
        await workspace.get_workspace_agentfs("s1")
        await workspace.get_workspace_agentfs("s2")
        await workspace.get_workspace_agentfs("s3")  # evicts s1
        assert len(opened) == 3
        assert len(closed) == 1  # only s1 evicted so far
    finally:
        await workspace.close_workspace_agentfs()

    # close_workspace_agentfs closes every remaining session
    assert len(closed) == 3


async def test_workspace_db_files_per_session(tmp_path, monkeypatch):
    """Each session gets its own DB file under .agentfs/workspace/."""
    monkeypatch.setattr(workspace, "WORKSPACE_AGENTFS_DIR", tmp_path)
    monkeypatch.setattr(workspace, "_SESSION_CACHE_MAX", 10)
    try:
        await workspace.write_file("sess-1", "/a.txt", "one")
        await workspace.write_file("sess-2", "/a.txt", "two")
        assert (tmp_path / "sess-1.db").exists()
        assert (tmp_path / "sess-2.db").exists()
        assert await workspace.read_file("sess-1", "/a.txt") is not None
        assert "two" in (await workspace.read_file("sess-2", "/a.txt") or "")
    finally:
        await workspace.close_workspace_agentfs()


async def test_io_prepare_trims_group_protocols_in_private(monkeypatch):
    from pydantic_ai import ToolDefinition as _TD

    async def _visible(chat_id, user_id, desc):
        deps = datatype.ContextDeps(
            client=cast(Client, SimpleNamespace()),
            user_id=user_id,
            chat_id=chat_id,
            message=cast(Message, SimpleNamespace(id=1, guest_query_id=None)),
        )
        ctx = RunContext(deps=deps, model=TestModel(), usage=RunUsage(), messages=[])
        td = _TD(name="read", description=desc, parameters_json_schema={})
        result = await io.prepare_io_tools(ctx, td)
        return result

    desc_with_group = (
        "- kmua://x — codebase\n"
        "- chat://info — current group info\n"
        "- chat://history?direction=latest — group messages\n"
        "- memory:// — group memory\n"
        "- https://x — web page"
    )
    # private: chat:// and memory:// lines removed
    td = await _visible(1001, 1001, desc_with_group)
    assert td is not None
    assert "chat://" not in (td.description or "")
    assert "memory://" not in (td.description or "")
    assert "kmua://" in (td.description or "")
    # group: description untouched
    td2 = await _visible(-100123, 1001, desc_with_group)
    assert td2 is not None
    assert "chat://info" in (td2.description or "")


async def test_delete_removes_file(ws):
    result = await io.delete(_ctx(), "work://hello.html")
    assert result == "Deleted work://hello.html."
    assert "File not found" in await io.read(_ctx(), "work://hello.html")
    assert "hello.html" not in await io.list(_ctx(), "work://")


async def test_delete_missing_file(ws):
    result = await io.delete(_ctx(), "work://nope.txt")
    assert "Error" in result


async def test_delete_rejects_codebase(ws):
    result = await io.delete(_ctx(), "kmua://kmua/x.py")
    assert "not deletable" in result


async def test_edit_with_line_number(ws):
    # line 2 only: replace "line" on that line, leave others untouched
    result = await io.edit(_ctx(), "work://demo.py", "line", "LINE", line=2)
    assert "Edited" in result
    content = await io.read(_ctx(), "work://demo.py")
    assert "LINE2" in content
    assert "line1" in content  # line 1 untouched
    assert "line3" in content  # line 3 untouched


async def test_edit_line_out_of_range(ws):
    result = await io.edit(_ctx(), "work://demo.py", "x", "y", line=99)
    assert "out of range" in result


async def test_edit_line_missing_text(ws):
    result = await io.edit(_ctx(), "work://demo.py", "zzz", "y", line=1)
    assert "not found on line 1" in result


# ------------------------------------------------------------ t.me message links


def _fake_message(**overrides):
    fields = dict(
        id=2333,
        from_user=None,
        sender_chat=SimpleNamespace(title="Some Channel"),
        date=None,
        text="Hello from the channel!",
        caption=None,
        photo=None,
        video=None,
        audio=None,
        voice=None,
        document=None,
        sticker=None,
        poll=None,
        forward_from=None,
        forward_from_chat=None,
        forward_from_message_id=None,
        reply_to_message=None,
        reply_to_top_message_id=None,
        topic_message=False,
        media=None,
    )
    fields.update(overrides)
    return SimpleNamespace(**fields)


async def test_read_tme_text_post(ws, monkeypatch):
    """A public t.me text post returns the message content, not an error."""

    async def fake_fetch(ctx, url):
        return SimpleNamespace(success=True, url=url, content="From: Chan")

    monkeypatch.setattr(io.web, "_fetch_telegram_message", fake_fetch)
    result = await io.read(_ctx(), "https://t.me/somechannel/2333")
    assert result == "From: Chan"


async def test_read_tme_media_post_notes_media_not_bytes(ws, monkeypatch):
    """A media post formats caption + media marker instead of binary garbage."""

    async def fake_fetch(ctx, url):
        return SimpleNamespace(
            success=True,
            url=url,
            content="From: Chan\n\n--- Content ---\n[Caption]: look\n[Contains photo]",
        )

    monkeypatch.setattr(io.web, "_fetch_telegram_message", fake_fetch)

    async def fail_download(ctx, url):
        raise AssertionError("media bytes must not be downloaded for read")

    monkeypatch.setattr(io, "_download_tme_media", fail_download)
    result = await io.read(_ctx(), "https://t.me/somechannel/2333")
    assert "[Contains photo]" in result
    assert "[Caption]: look" in result


async def test_read_tme_unresolvable_falls_back_to_web_page(ws, monkeypatch):
    """When the client cannot resolve the chat, the t.me web page is used."""

    async def fake_fetch(ctx, url):
        return SimpleNamespace(success=False, url=url, error="Cannot access")

    monkeypatch.setattr(io.web, "_fetch_telegram_message", fake_fetch)

    async def fake_http(url):
        return SimpleNamespace(success=True, url=url, content="Channel post text")

    monkeypatch.setattr(io.web, "_fetch_http", fake_http)
    result = await io.read(_ctx(), "https://t.me/somechannel/2333")
    assert result == "Channel post text"


async def test_read_tme_all_paths_fail(ws, monkeypatch):
    async def fake_fetch(ctx, url):
        return SimpleNamespace(success=False, url=url, error="Cannot access")

    monkeypatch.setattr(io.web, "_fetch_telegram_message", fake_fetch)

    async def fail_http(url):
        raise AssertionError("crawl api is not configured; must use _fetch_http")

    monkeypatch.setattr(io.web, "_fetch_crawl_api", fail_http)

    async def fake_http(url):
        return SimpleNamespace(success=False, url=url, error="page gone")

    monkeypatch.setattr(io.web, "_fetch_http", fake_http)
    result = await io.read(_ctx(), "https://t.me/somechannel/2333")
    assert "page gone" in result


async def test_read_tme_private_share_link_rejected(ws):
    result = await io.read(_ctx(), "https://t.me/c/1234567/2333")
    assert "Error" in result


async def test_read_tme_paging(ws, monkeypatch):
    async def fake_fetch(ctx, url):
        return SimpleNamespace(success=True, url=url, content="l1\nl2\nl3")

    monkeypatch.setattr(io.web, "_fetch_telegram_message", fake_fetch)
    result = await io.read(
        _ctx(), "https://t.me/somechannel/2333", start_line=2, max_lines=1
    )
    assert result == "l2"
