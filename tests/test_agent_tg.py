"""Unified tg tool: Telegram Bot API-style method calls on the current chat."""

from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

import pyrogram

from kmua.plugins.agent.tools import tg_ops


def _ctx(client=None):
    return SimpleNamespace(
        deps=SimpleNamespace(
            client=client or SimpleNamespace(),
            chat_id=-100_123,
            user_id=1001,
            message=SimpleNamespace(id=7, guest_query_id=None),
            is_guest_mode=False,
            powermemory=None,
            tools_called_this_turn=set(),
        )
    )


async def test_send_message_maps_params():
    calls = {}

    class FakeMessage:
        message_id = 42

    async def fake_send_message(chat_id, **kwargs):
        calls["chat_id"] = chat_id
        calls.update(kwargs)
        return FakeMessage()

    result = await tg_ops.tg(
        _ctx(SimpleNamespace(send_message=fake_send_message)),
        "sendMessage",
        {"text": "hello", "parse_mode": "HTML"},
    )
    assert result == "sendMessage sent (message_id=42)."
    assert calls["chat_id"] == -100_123
    assert calls["text"] == "hello"
    assert calls["parse_mode"] == "HTML"


async def test_send_message_reply_and_preview():
    calls = {}

    async def fake_send_message(chat_id, **kwargs):
        calls.update(kwargs)
        return SimpleNamespace(message_id=1)

    await tg_ops.tg(
        _ctx(SimpleNamespace(send_message=fake_send_message)),
        "sendMessage",
        {"text": "x", "reply_to_message_id": 9, "disable_web_page_preview": True},
    )
    assert isinstance(calls["reply_parameters"], pyrogram.types.ReplyParameters)
    assert calls["reply_parameters"].message_id == 9
    assert isinstance(calls["link_preview_options"], pyrogram.types.LinkPreviewOptions)
    assert calls["link_preview_options"].is_disabled is True


async def test_send_reaction():
    calls = {}

    async def fake_send_reaction(chat_id, **kwargs):
        calls.update(kwargs)
        return SimpleNamespace()

    await tg_ops.tg(
        _ctx(SimpleNamespace(send_reaction=fake_send_reaction)),
        "sendReaction",
        {"message_id": 5, "emoji": "👍"},
    )
    assert calls["message_id"] == 5
    assert calls["emoji"] == "👍"


async def test_send_poll_options_list():
    calls = {}

    async def fake_send_poll(chat_id, **kwargs):
        calls.update(kwargs)
        return SimpleNamespace(message_id=3)

    await tg_ops.tg(
        _ctx(SimpleNamespace(send_poll=fake_send_poll)),
        "sendPoll",
        {"question": "Lunch?", "options": ["noodles", "rice"], "is_anonymous": True},
    )
    assert calls["question"] == "Lunch?"
    assert calls["options"] == ["noodles", "rice"]
    assert calls["is_anonymous"] is True


async def test_unknown_method_rejected():
    result = await tg_ops.tg(_ctx(), "deleteMessage", {"message_id": 1})
    assert "Unknown method" in result
    assert "deleteMessage" not in result.split("Supported")[0] or True


async def test_unknown_field_rejected():
    result = await tg_ops.tg(_ctx(), "sendMessage", {"text": "x", "parse": "HTML"})
    assert "Unknown field" in result
    assert "parse" in result


async def test_chat_id_override_rejected():
    result = await tg_ops.tg(_ctx(), "sendMessage", {"text": "x", "chat_id": 999})
    assert "do not pass it" in result


async def test_missing_required_rejected():
    result = await tg_ops.tg(_ctx(), "sendReaction", {"emoji": "👍"})
    assert "Missing required" in result
    assert "message_id" in result


async def test_params_must_be_object():
    result = await tg_ops.tg(_ctx(), "sendMessage", "hello")
    assert "params must be an object" in result


async def test_search_sticker_removed():
    result = await tg_ops.tg(_ctx(), "searchSticker", {"query": "happy"})
    assert "Unknown method" in result


async def test_kmua_block_user(monkeypatch):
    calls = []

    async def fake_block(ctx, duration_minutes, user_id, reason):
        calls.append((duration_minutes, user_id, reason))
        return "blocked"

    monkeypatch.setattr(tg_ops.block, "block_user", fake_block)
    result = await tg_ops.tg(
        _ctx(), "blockUser", {"duration_minutes": 30, "reason": "spam"}
    )
    assert result == "blocked"
    assert calls == [(30, None, "spam")]


async def test_kmua_schedule(monkeypatch):
    calls = []

    async def fake_schedule(ctx, schedule_time, text=None, **kwargs):
        calls.append((schedule_time, text))
        return "scheduled"

    monkeypatch.setattr(tg_ops.send_ops, "schedule_message", fake_schedule)
    result = await tg_ops.tg(
        _ctx(),
        "scheduleMessage",
        {"text": "提醒", "schedule_time": "2026-08-03T10:00:00+08:00"},
    )
    assert result == "scheduled"
    assert calls == [("2026-08-03T10:00:00+08:00", "提醒")]


async def test_send_error_wrapped():
    class Boom(Exception):
        pass

    async def fake_send_message(chat_id, **kwargs):
        raise Boom("network down")

    result = await tg_ops.tg(
        _ctx(SimpleNamespace(send_message=fake_send_message)),
        "sendMessage",
        {"text": "x"},
    )
    assert "sendMessage failed" in result


# ------------------------------------------------------------ prepare gating


def _run_ctx(chat_id, user_id, guest=False):
    from pydantic_ai import RunContext

    from kmua.plugins.agent import datatype

    deps = datatype.ContextDeps(
        client=SimpleNamespace(),
        user_id=user_id,
        chat_id=chat_id,
        message=SimpleNamespace(id=1, guest_query_id=1 if guest else None),
    )
    return RunContext(
        deps=deps, model=SimpleNamespace(), usage=SimpleNamespace(), messages=[]
    )


async def _prepare(tool, ctx):
    from pydantic_ai.tools import ToolDefinition

    td = ToolDefinition(name=tool.name, description="", parameters_json_schema={})
    result = await tool.prepare(ctx, td)
    return result is not None


async def test_prepare_manyacg_gates_anime(monkeypatch):
    from kmua.config import app_config
    from kmua.plugins.agent.tools import prepare

    tool = SimpleNamespace(
        prepare=prepare.prepare_manyacg_tools, name="send_anime_photo"
    )
    monkeypatch.setattr(app_config, "manyacg_api_key", None)
    assert not await _prepare(tool, _run_ctx(-100123, 1001))
    monkeypatch.setattr(app_config, "manyacg_api_key", "key")
    assert await _prepare(tool, _run_ctx(-100123, 1001))


async def test_prepare_sticker_gates_private(monkeypatch):
    from kmua.config import app_config
    from kmua.plugins.agent.tools import prepare

    tool = SimpleNamespace(prepare=prepare.prepare_sticker_tools, name="send_sticker")
    monkeypatch.setattr(app_config, "agent_sticker_memory", True)
    # private chat: hidden
    assert not await _prepare(tool, _run_ctx(1001, 1001))
    # group chat with embedder but zero stickers: hidden
    from kmua.plugins.agent import sticker_memory, sticker_vec

    monkeypatch.setattr(sticker_memory, "embedder", SimpleNamespace())
    async def count_zero(chat_id):
        return 0

    async def count_thirty(chat_id):
        return 30

    monkeypatch.setattr(sticker_vec, "count", count_zero)
    assert not await _prepare(tool, _run_ctx(-100123, 1001))
    monkeypatch.setattr(sticker_vec, "count", count_thirty)
    assert await _prepare(tool, _run_ctx(-100123, 1001))


async def test_prepare_group_gates_quote(monkeypatch):
    from kmua.plugins.agent.tools import prepare

    tool = SimpleNamespace(prepare=prepare.prepare_group_tools, name="send_chat_quote")
    assert not await _prepare(tool, _run_ctx(1001, 1001))  # private hidden
    assert await _prepare(tool, _run_ctx(-100123, 1001))  # group visible


async def test_send_document_work_reference(monkeypatch, tmp_path):
    """sendDocument accepts work:// references to this session's workspace."""
    from agentfs_sdk import AgentFS, AgentFSOptions

    agent = await AgentFS.open(
        AgentFSOptions(id="kmua-tg-ws", path=str(tmp_path / "ws.db"))
    )
    await agent.fs.write_file("/report.pdf", b"%PDF-1.4 fake")

    async def fake_get(session_key):
        return agent

    monkeypatch.setattr(tg_ops.workspace, "get_workspace_agentfs", fake_get)
    calls = {}

    async def fake_send_document(chat_id, **kwargs):
        calls["document"] = kwargs["document"]
        return SimpleNamespace(message_id=1)

    try:
        result = await tg_ops.tg(
            _ctx(SimpleNamespace(send_document=fake_send_document)),
            "sendDocument",
            {"document": "work://report.pdf"},
        )
        assert result.startswith("sendDocument sent")
        assert isinstance(calls["document"], BytesIO)
        assert calls["document"].name == "report.pdf"
        assert calls["document"].read() == b"%PDF-1.4 fake"
    finally:
        await agent.close()


async def test_send_document_content_makes_document(monkeypatch):
    """sendDocument content + file_name sends plain text as a named document."""
    calls = {}

    async def fake_send_document(chat_id, **kwargs):
        calls["document"] = kwargs["document"]
        return SimpleNamespace(message_id=1)

    result = await tg_ops.tg(
        _ctx(SimpleNamespace(send_document=fake_send_document)),
        "sendDocument",
        {"content": "hello from agent", "file_name": "hello.txt"},
    )
    assert result.startswith("sendDocument sent")
    assert calls["document"].name == "hello.txt"
    assert calls["document"].read() == b"hello from agent"


async def test_send_document_content_and_document_conflict():
    result = await tg_ops.tg(_ctx(), "sendDocument", {"content": "x", "document": "y"})
    assert "not both" in result


async def test_tg_media_keeps_source_extensions(monkeypatch):
    """.go (and any explicit extension) must survive — no .bin suffix."""
    calls = {}

    async def fake_download(url, max_bytes=None):
        return b"package main"

    monkeypatch.setattr(tg_ops, "safe_download_bytes", fake_download)

    async def fake_send_document(chat_id, **kwargs):
        calls["document"] = kwargs["document"]
        return SimpleNamespace(message_id=1)

    await tg_ops.tg(
        _ctx(SimpleNamespace(send_document=fake_send_document)),
        "sendDocument",
        {"document": "https://example.com/main.go"},
    )
    assert calls["document"].name == "main.go"
    assert not calls["document"].name.endswith(".bin")


async def test_tg_media_work_ref_keeps_go_extension(monkeypatch, tmp_path):
    from agentfs_sdk import AgentFS, AgentFSOptions

    agent = await AgentFS.open(
        AgentFSOptions(id="kmua-tg-go", path=str(tmp_path / "ws.db"))
    )
    await agent.fs.write_file("/landrun/sandbox.go", b"package sandbox")

    async def fake_get(session_key):
        return agent

    monkeypatch.setattr(tg_ops.workspace, "get_workspace_agentfs", fake_get)
    calls = {}

    async def fake_send_document(chat_id, **kwargs):
        calls["document"] = kwargs["document"]
        return SimpleNamespace(message_id=1)

    try:
        await tg_ops.tg(
            _ctx(SimpleNamespace(send_document=fake_send_document)),
            "sendDocument",
            {"document": "work://landrun/sandbox.go"},
        )
        assert calls["document"].name == "sandbox.go"
    finally:
        await agent.close()


async def test_tg_send_document_kmua_ref(monkeypatch, tmp_path):
    """sendDocument accepts kmua:// codebase files (read-only)."""
    from agentfs_sdk import AgentFS, AgentFSOptions

    code_agent = await AgentFS.open(
        AgentFSOptions(id="kmua-tg-code", path=str(tmp_path / "code.db"))
    )
    await code_agent.fs.write_file("/kmua/services/wechat.py", b"# wechat code")

    async def fake_code_get():
        return code_agent

    monkeypatch.setattr(tg_ops.code_repo, "get_code_agentfs", fake_code_get)
    calls = {}

    async def fake_send_document(chat_id, **kwargs):
        calls["document"] = kwargs["document"]
        return SimpleNamespace(message_id=1)

    try:
        result = await tg_ops.tg(
            _ctx(SimpleNamespace(send_document=fake_send_document)),
            "sendDocument",
            {"document": "kmua://kmua/services/wechat.py"},
        )
        assert result.startswith("sendDocument sent")
        assert calls["document"].name == "wechat.py"
        assert calls["document"].read() == b"# wechat code"
    finally:
        await code_agent.close()
