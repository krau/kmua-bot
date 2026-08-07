"""persist:// and sandbox:// protocol contracts in the unified io tools."""

from __future__ import annotations

import asyncio
import os
import time
from types import SimpleNamespace

import pytest
from pydantic_ai import RunContext, RunUsage
from pydantic_ai.models.test import TestModel

from kmua.database import persistent_file as pf
from kmua.plugins.agent import datatype
from kmua.plugins.agent.tools import io, workspace
from kmua.services import sandbox

pytestmark = pytest.mark.usefixtures("initialised_db")


@pytest.fixture(autouse=True)
async def _close_agentfs():
    """agentfs keeps SQLite connections bound to the loop that opened them;
    close per test so a later test's new loop never reuses them."""
    yield
    await workspace.close_workspace_agentfs()


@pytest.fixture
def ctx():
    return RunContext(
        deps=SimpleNamespace(
            chat_id=-100123,
            user_id=999,
            instructions="",
            powermemory=None,
        ),
        model=TestModel(),
        usage=RunUsage(),
    )


@pytest.fixture
def sandbox_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "shell_root_dir", lambda: tmp_path)
    workdir = tmp_path / "-100123"
    workdir.mkdir(parents=True)
    return workdir


def _fake_client(sent=None, file_chunks=None):

    class FakeClient:
        def __init__(self):
            self.sent = None
            self.sent_kwargs = None
            self.file_chunks = file_chunks or [b"filedata"]

        async def send_document(self, chat_id, **kwargs):
            self.sent = chat_id
            self.sent_kwargs = kwargs
            return sent

        def get_file(self, file_id):
            async def gen():
                for chunk in self.file_chunks:
                    yield chunk

            return gen()

    return FakeClient()


# ---- persist:// write / read / list / delete ----


def _sent_message(file_id="tg_fid", name="report.txt"):
    return SimpleNamespace(
        id=77,
        document=SimpleNamespace(
            file_id=file_id,
            file_unique_id="tg_fuid",
            file_name=name,
            mime_type="text/plain",
            file_size=11,
        ),
    )


async def test_write_persist_sends_document_and_records(ctx, monkeypatch):
    sent = _sent_message()
    fake = _fake_client(sent=sent)
    ctx.deps.client = fake

    result = await io.write(ctx, "persist://report.txt", "hello world")
    assert "Persisted report.txt" in result
    assert fake.sent == -100123
    assert fake.sent_kwargs is not None
    assert fake.sent_kwargs["file_name"] == "report.txt"
    record = await pf.get_persistent_file(-100123, "report.txt")
    assert record is not None
    assert record.file_id == "tg_fid"
    assert record.tg_message_id == 77


async def test_write_persist_reference_keeps_bytes(ctx, monkeypatch, sandbox_dir):
    """A sandbox:// reference payload is persisted as raw bytes, not text."""
    sent = _sent_message()
    fake = _fake_client(sent=sent)
    ctx.deps.client = fake
    (sandbox_dir / "data.bin").write_bytes(b"\x00\x01binary")

    result = await io.write(ctx, "persist://data.bin", "sandbox://data.bin")
    assert "Persisted data.bin" in result
    assert fake.sent_kwargs is not None
    assert fake.sent_kwargs["file_name"] == "data.bin"
    assert fake.sent_kwargs["document"].getvalue() == b"\x00\x01binary"


async def test_write_persist_overwrites_same_name(ctx, monkeypatch):
    fake = _fake_client(sent=_sent_message(file_id="fid2"))
    ctx.deps.client = fake
    await io.write(ctx, "persist://report.txt", "v1")
    await io.write(ctx, "persist://report.txt", "v2")
    record = await pf.get_persistent_file(-100123, "report.txt")
    assert record is not None
    assert record.file_id == "fid2"
    assert (await pf.list_persistent_files(-100123))[0].description is None


async def test_read_persist_downloads_and_pages(ctx, monkeypatch):
    fake = _fake_client(file_chunks=[b"line1\nline2\nline3"])
    ctx.deps.client = fake
    await pf.upsert_persistent_file(
        -100123, "notes", None, 1, "tg_fid", "tg_fuid", None, None, 17
    )
    from pyrogram.file_id import FileId

    monkeypatch.setattr(FileId, "decode", staticmethod(lambda _: object()))

    result = await io.read(ctx, "persist://notes", start_line=2, max_lines=5)
    assert result == "line2\nline3"


async def test_list_persist_shows_records(ctx):
    await pf.upsert_persistent_file(
        -100123, "a.txt", None, 1, "fid", "fuid", None, None, 2048
    )
    await pf.upsert_persistent_file(
        -100123, "b.txt", None, 2, "fid2", "fuid2", None, None, 1024
    )
    result = await io.list(ctx, "persist://")
    assert "a.txt" in result and "b.txt" in result
    assert "2.0 KB" in result


async def test_delete_persist_keeps_chat_message(ctx):
    await pf.upsert_persistent_file(
        -100123, "notes", None, 1, "fid", "fuid", None, None, None
    )
    result = await io.delete(ctx, "persist://notes")
    assert "Removed notes" in result and "stays" in result
    assert await pf.get_persistent_file(-100123, "notes") is None
    assert await pf.delete_persistent_file(-100123, "notes") is False


async def test_persist_scope_isolated_between_chats(ctx, monkeypatch):
    fake = _fake_client(sent=_sent_message())
    ctx.deps.client = fake
    await io.write(ctx, "persist://report.txt", "x")
    # Another chat cannot read or list this chat's files.
    other = RunContext(
        deps=datatype.ContextDeps(
            client=object(),  # type: ignore[arg-type]
            user_id=999,
            chat_id=-200,
            message=object(),  # type: ignore[arg-type]
        ),
        model=TestModel(),
        usage=RunUsage(),
    )
    result = await io.read(other, "persist://report.txt")
    assert "No persisted file named 'report.txt'" in result


# ---- sandbox:// read / write / list / delete ----


async def test_write_sandbox_and_read_back(ctx, sandbox_dir):
    result = await io.write(ctx, "sandbox://out/data.txt", "hello sandbox")
    assert "Wrote" in result
    assert (sandbox_dir / "out" / "data.txt").read_text() == "hello sandbox"

    result = await io.read(ctx, "sandbox://out/data.txt", start_line=1, max_lines=10)
    assert "hello sandbox" in result


async def test_list_sandbox(ctx, sandbox_dir):
    (sandbox_dir / "a.txt").write_text("x")
    (sandbox_dir / "sub").mkdir()
    result = await io.list(ctx, "sandbox://")
    assert "a.txt" in result
    assert "sub" in result and "dir" in result


async def test_delete_sandbox(ctx, sandbox_dir):
    (sandbox_dir / "a.txt").write_text("x")
    result = await io.delete(ctx, "sandbox://a.txt")
    assert "Deleted" in result
    assert not (sandbox_dir / "a.txt").exists()


async def test_sandbox_path_escape_rejected(ctx, sandbox_dir):
    result = await io.write(ctx, "sandbox://../evil.txt", "x")
    assert "Error" in result
    assert not (sandbox_dir.parent / "evil.txt").exists()


# ---- local workspace sweeps (retention) ----


async def test_cleanup_stale_sessions_removes_old_only(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "shell_root_dir", lambda: tmp_path)
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    (fresh / "f.txt").write_text("x")
    stale = tmp_path / "stale"
    stale.mkdir()
    (stale / "f.txt").write_text("x")
    old = time.time() - 40 * 86400
    os.utime(stale / "f.txt", (old, old))
    os.utime(stale, (old, old))

    assert await sandbox.cleanup_stale_sessions(30) == 1
    assert fresh.exists()
    assert not stale.exists()


async def test_cleanup_stale_workspaces_removes_old_only(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "WORKSPACE_AGENTFS_DIR", tmp_path)
    (tmp_path / "fresh.db").touch()
    (tmp_path / "stale.db").touch()
    old = time.time() - 40 * 86400
    os.utime(tmp_path / "stale.db", (old, old))

    assert await workspace.cleanup_stale_workspaces(30) == 1
    assert (tmp_path / "fresh.db").exists()
    assert not (tmp_path / "stale.db").exists()


async def test_delete_workspace_session_closes_and_removes(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "WORKSPACE_AGENTFS_DIR", tmp_path)
    db_path = tmp_path / "s1.db"
    db_path.touch()
    closed = []

    class FakeAgent:
        async def close(self):
            closed.append(True)

    workspace._workspace_agentfs["s1"] = FakeAgent()  # type: ignore[assignment]
    await workspace.delete_workspace_session("s1")
    assert closed == [True]
    assert not db_path.exists()
    assert "s1" not in workspace._workspace_agentfs
    workspace._workspace_agentfs.clear()


async def test_sandbox_symlink_read_rejected(ctx, sandbox_dir, tmp_path):
    """A sandbox symlink pointing outside must not be followed by io."""
    secret = tmp_path / "secret.txt"
    secret.write_text("top-secret")
    (sandbox_dir / "evil").symlink_to(secret)

    result = await io.read(ctx, "sandbox://evil")
    assert "Error" in result
    assert "top-secret" not in result


async def test_sandbox_symlink_write_rejected(ctx, sandbox_dir, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("original")
    (sandbox_dir / "evil").symlink_to(secret)

    result = await io.write(ctx, "sandbox://evil", "overwritten")
    assert "Error" in result
    assert secret.read_text() == "original"


async def test_sandbox_symlink_delete_rejected(ctx, sandbox_dir, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("original")
    (sandbox_dir / "evil").symlink_to(secret)

    result = await io.delete(ctx, "sandbox://evil")
    assert "Error" in result
    assert secret.exists()


async def test_cleanup_keeps_workspace_with_fresh_wal(tmp_path, monkeypatch):
    """WAL mode: writes touch the -wal sidecar, so a workspace written today
    must not be swept even when its main db file is old."""
    monkeypatch.setattr(workspace, "WORKSPACE_AGENTFS_DIR", tmp_path)
    db_path = tmp_path / "active.db"
    db_path.touch()
    old = time.time() - 40 * 86400
    os.utime(db_path, (old, old))
    (tmp_path / "active.db-wal").touch()  # fresh sidecar = recent write

    assert await workspace.cleanup_stale_workspaces(30) == 0
    assert db_path.exists()


async def test_clear_conversation_session_private_cleans_files(monkeypatch, tmp_path):
    """The shared helper clears workspace files in private chats (used by
    both /forget and the clear-history button)."""
    from kmua.plugins.agent import agent as agent_mod

    monkeypatch.setattr(sandbox, "shell_root_dir", lambda: tmp_path)
    monkeypatch.setattr(workspace, "WORKSPACE_AGENTFS_DIR", tmp_path)
    (tmp_path / "999.db").touch()
    workdir = tmp_path / "999"
    workdir.mkdir()
    (workdir / "f.txt").write_text("x")
    await agent_mod.common.memttlcache.set("message_history_with_agent:999:999", b"h")

    await agent_mod._clear_conversation_session(999, 999)

    assert not (tmp_path / "999.db").exists()
    assert not (workdir / "f.txt").exists()
    assert (
        await agent_mod.common.memttlcache.get("message_history_with_agent:999:999")
        is None
    )


async def test_clear_conversation_session_group_keeps_files(monkeypatch, tmp_path):
    """Group chats share their sandbox: the helper must not touch files."""
    from kmua.plugins.agent import agent as agent_mod

    monkeypatch.setattr(sandbox, "shell_root_dir", lambda: tmp_path)
    monkeypatch.setattr(workspace, "WORKSPACE_AGENTFS_DIR", tmp_path)
    (tmp_path / "-100.db").touch()

    await agent_mod._clear_conversation_session(-100, 555)

    assert (tmp_path / "-100.db").exists()


def test_upsert_stmt_supports_all_supported_dialects():
    """SQLite, PostgreSQL and MySQL must each compile their own upsert; an
    unknown dialect is rejected instead of guessing."""
    from sqlalchemy.dialects import mysql, postgresql, sqlite

    values = {
        "chat_id": -1,
        "name": "n",
        "description": None,
        "tg_message_id": 1,
        "file_id": "f",
        "file_unique_id": "fu",
        "file_name": None,
        "mime_type": None,
        "file_size": None,
    }
    sql = str(pf._upsert_stmt(values, "sqlite").compile(dialect=sqlite.dialect()))
    assert "ON CONFLICT" in sql
    sql = str(
        pf._upsert_stmt(values, "postgresql").compile(dialect=postgresql.dialect())
    )
    assert "ON CONFLICT" in sql
    sql = str(pf._upsert_stmt(values, "mysql").compile(dialect=mysql.dialect()))
    assert "ON DUPLICATE KEY UPDATE" in sql
    with pytest.raises(ValueError):
        pf._upsert_stmt(values, "oracle")


async def test_delete_workspace_session_removes_wal_sidecars(tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.setattr(workspace, "WORKSPACE_AGENTFS_DIR", tmp_path)
    db_path = tmp_path / "s1.db"
    for suffix in ("", "-wal", "-shm"):
        Path(f"{db_path}{suffix}").touch()
    closed = []

    class FakeAgent:
        async def close(self):
            closed.append(True)

    workspace._workspace_agentfs["s1"] = FakeAgent()  # type: ignore[assignment]
    await workspace.delete_workspace_session("s1")
    assert closed == [True]
    for suffix in ("", "-wal", "-shm"):
        assert not Path(f"{db_path}{suffix}").exists()
    workspace._workspace_agentfs.clear()


# ---- chat://media protocol (download a chat message's media) ----


def _tg_client(message=None, media_data=b"filedata"):

    class FakeMessage:
        media = True
        document = SimpleNamespace(file_size=len(media_data))

    if message is None:
        message = FakeMessage()

    class FakeClient:
        def __init__(self):
            self.downloaded = []
            self.sent = None
            self.sent_kwargs = None

        async def get_messages(self, chat_id, msg_id):
            assert chat_id == -100123, "must be scoped to the current chat"
            return message

        async def download_media(self, message, in_memory=True):
            self.downloaded.append(message)
            from io import BytesIO

            return BytesIO(media_data)

        async def send_document(self, chat_id, **kwargs):
            self.sent = chat_id
            self.sent_kwargs = kwargs
            return _sent_message()

    return FakeClient()


async def test_write_tg_reference_downloads_into_workspace(ctx, monkeypatch):
    fake = _tg_client(media_data=b"tg-content")
    ctx.deps.client = fake
    result = await io.write(ctx, "work://dl.txt", "chat://media/123")
    assert "Wrote 10 bytes" in result
    assert await workspace.read_file_bytes("-100123", "/dl.txt") == b"tg-content"


async def test_write_tg_reference_into_sandbox(ctx, monkeypatch, sandbox_dir):
    fake = _tg_client(media_data=b"sandbox-data")
    ctx.deps.client = fake
    result = await io.write(ctx, "sandbox://dl.bin", "chat://media/123")
    assert "Wrote" in result
    assert (sandbox_dir / "dl.bin").read_bytes() == b"sandbox-data"


async def test_write_tg_reference_persists(ctx, monkeypatch):
    fake = _tg_client(media_data=b"persist-me")
    ctx.deps.client = fake
    result = await io.write(ctx, "persist://dl.txt", "chat://media/123")
    assert "Persisted dl.txt" in result
    assert fake.sent_kwargs is not None
    assert fake.sent_kwargs["document"].getvalue() == b"persist-me"


async def test_tg_reference_rejects_non_numeric_id(ctx, monkeypatch):
    result = await io.write(ctx, "work://x", "chat://media/abc")
    assert "expected a message id" in result


async def test_tg_reference_rejects_message_without_media(ctx, monkeypatch):
    fake = _tg_client(message=SimpleNamespace(media=False))
    ctx.deps.client = fake
    result = await io.write(ctx, "work://x", "chat://media/123")
    assert "no downloadable media" in result


async def test_tg_reference_rejects_oversize_before_download(ctx, monkeypatch):
    """The size cap is checked from the message metadata before downloading."""
    from kmua.config import app_config

    big = SimpleNamespace(media=True, document=SimpleNamespace(file_size=30_000_000))
    fake = _tg_client(message=big)
    ctx.deps.client = fake
    monkeypatch.setattr(app_config, "agent_download_max_bytes", 20_000_000)
    result = await io.write(ctx, "work://x", "chat://media/123")
    assert "over the 20000000 byte download limit" in result
    assert fake.downloaded == []


async def test_read_tg_reference_returns_text_content(ctx, monkeypatch):
    fake = _tg_client(media_data=b"line1\nline2\nline3")
    ctx.deps.client = fake
    result = await io.read(ctx, "chat://media/123", start_line=2, max_lines=5)
    assert result == "line2\nline3"


# ---- https://t.me links (public Telegram media) ----


def _tg_public_client(media_data=b"public-data"):

    class FakeChat:
        id = -100123456789

    class FakeMessage:
        media = True
        document = SimpleNamespace(file_size=len(media_data))

    class FakeClient:
        def __init__(self):
            self.downloaded = []

        async def get_chat(self, ref):
            assert ref == "MoreACG"
            return FakeChat()

        async def get_messages(self, chat_id, msg_id):
            self.last_chat = chat_id
            assert msg_id == 27411
            return FakeMessage()

        async def download_media(self, message, in_memory=True):
            self.downloaded.append(message)
            from io import BytesIO

            return BytesIO(media_data)

    return FakeClient()


async def test_write_tg_link_downloads_public_media(ctx, monkeypatch):
    fake = _tg_public_client(media_data=b"public-data")
    ctx.deps.client = fake
    result = await io.write(ctx, "work://dl.txt", "https://t.me/MoreACG/27411")
    assert "Wrote" in result
    assert await workspace.read_file_bytes("-100123", "/dl.txt") == b"public-data"
    assert fake.last_chat == -100123456789


async def test_tme_link_telegram_me_host(ctx, monkeypatch):
    fake = _tg_public_client()
    ctx.deps.client = fake
    result = await io.write(ctx, "sandbox://x", "https://telegram.me/MoreACG/27411")
    assert "Wrote" in result


async def test_tme_link_invalid_format(ctx, monkeypatch):
    result = await io.write(ctx, "work://x", "https://t.me/MoreACG")
    assert "Not a t.me message link" in result


async def test_read_tg_link_returns_text(ctx, monkeypatch):
    fake = _tg_public_client(media_data=b"a\nb\nc")
    ctx.deps.client = fake
    result = await io.read(ctx, "https://t.me/MoreACG/27411", start_line=2, max_lines=5)
    assert result == "b\nc"


# ---- https direct-file links (write references) ----


async def test_http_reference_downloads_direct_link(ctx, monkeypatch):
    """A plain https file link is downloaded through the SSRF-guarded
    downloader with the configured size cap."""
    from kmua.config import app_config
    from kmua.plugins.agent.tools import io as io_mod

    captured = {}

    async def fake_download(url, max_bytes):
        captured["url"] = url
        captured["max_bytes"] = max_bytes
        return b"direct-file-data"

    monkeypatch.setattr(io_mod, "safe_download_bytes", fake_download)
    monkeypatch.setattr(
        io_mod,
        "UnsafeUrlError",
        __import__("kmua.common.safe_http", fromlist=["UnsafeUrlError"]).UnsafeUrlError,
    )
    monkeypatch.setattr(app_config, "agent_download_max_bytes", 5_000_000)

    result = await io.write(ctx, "work://dl.bin", "https://example.com/file.zip")
    assert "Wrote" in result
    assert captured == {
        "url": "https://example.com/file.zip",
        "max_bytes": 5_000_000,
    }
    assert await workspace.read_file_bytes("-100123", "/dl.bin") == b"direct-file-data"


async def test_http_reference_download_failure_is_clear(ctx, monkeypatch):
    from kmua.common.safe_http import UnsafeUrlError
    from kmua.plugins.agent.tools import io as io_mod

    async def fake_download(url, max_bytes):
        raise UnsafeUrlError("Unsafe URL: http://169.254.169.254/latest/meta-data")

    monkeypatch.setattr(io_mod, "safe_download_bytes", fake_download)
    monkeypatch.setattr(io_mod, "UnsafeUrlError", UnsafeUrlError)
    result = await io.write(ctx, "work://x", "https://169.254.169.254/latest")
    assert "Download failed" in result


# ---- review regressions ----


async def test_tme_link_rejects_private_channel_form(ctx, monkeypatch):
    """t.me/c/<id>/<msg> (private-channel shares) must be refused: reading
    media from private chats beyond the current conversation is out of
    scope for the agent."""
    result = await io.write(ctx, "work://x", "https://t.me/c/123456789/100")
    assert "Not a t.me message link" in result


async def test_read_tme_text_post_falls_back_to_web(ctx, monkeypatch):
    """A plain-text t.me post has no media; read must fall back to the web
    text extraction instead of failing."""
    from kmua.plugins.agent.tools import io as io_mod

    class FakeChat:
        id = -100123456789

    class FakeMessage:
        media = False

    class FakeClient:
        async def get_chat(self, ref):
            return FakeChat()

        async def get_messages(self, chat_id, msg_id):
            return FakeMessage()

    ctx.deps.client = FakeClient()

    captured = {}

    async def fake_fetch(ctx_arg, url):
        captured["url"] = url
        return SimpleNamespace(success=True, content="帖子的文本内容")

    monkeypatch.setattr(io_mod.web, "fetch_web_page", fake_fetch)
    result = await io.read(ctx, "https://t.me/SomeChannel/123")
    assert "帖子的文本内容" in result
    assert captured["url"] == "https://t.me/SomeChannel/123"


async def test_tg_download_rejects_paid_media(ctx, monkeypatch):
    """Paid media is refused before any download: its total size cannot be
    reliably known up front."""

    class FakeClient:
        async def get_messages(self, chat_id, msg_id):
            return SimpleNamespace(
                media=True, paid_media=SimpleNamespace(extended_media=[])
            )

        async def download_media(self, *args, **kwargs):
            raise AssertionError("paid media must not be downloaded")

    ctx.deps.client = FakeClient()
    result = await io.write(ctx, "work://x", "chat://media/1")
    assert "paid media is not supported" in result


async def test_tg_download_applies_timeout(ctx, monkeypatch):
    """The configured download timeout bounds the media fetch."""
    from kmua.config import app_config

    class FakeClient:
        async def get_messages(self, chat_id, msg_id):
            return SimpleNamespace(media=True, document=SimpleNamespace(file_size=5))

        async def download_media(self, message, in_memory=True):
            await asyncio.sleep(10)
            from io import BytesIO

            return BytesIO(b"x")

    ctx.deps.client = FakeClient()
    monkeypatch.setattr(app_config, "agent_download_timeout", 0.05)
    result = await io.write(ctx, "work://x", "chat://media/1")
    assert "Error" in result


async def test_read_tme_webpage_preview_falls_back(ctx, monkeypatch):
    """A plain-text post with a web-page preview (message.media is truthy
    but nothing is downloadable) must fall back to web text extraction."""
    from kmua.plugins.agent.tools import io as io_mod

    class FakeChat:
        id = -100123456789

    class FakeMessage:
        media = True
        web_page = SimpleNamespace(url="https://example.com")
        # no photo/document/video: nothing downloadable

    class FakeClient:
        async def get_chat(self, ref):
            return FakeChat()

        async def get_messages(self, chat_id, msg_id):
            return FakeMessage()

        async def download_media(self, *args, **kwargs):
            raise AssertionError("must not attempt a download")

    ctx.deps.client = FakeClient()
    captured = {}

    async def fake_fetch(ctx_arg, url):
        captured["url"] = url
        return SimpleNamespace(success=True, content="预览帖子的文本")

    monkeypatch.setattr(io_mod.web, "fetch_web_page", fake_fetch)
    result = await io.read(ctx, "https://t.me/SomeChannel/456")
    assert "预览帖子的文本" in result
    assert captured["url"] == "https://t.me/SomeChannel/456"


def test_format_search_results_uses_dict_fields():
    """Search results are dicts (title/href/body); attribute access would
    render every entry empty."""
    from kmua.plugins.agent.tools.io import _format_search_results

    results = [
        {"title": "白雪乃爱 - 维基", "href": "https://example.com/a", "body": "介绍"},
        {"title": "角色主页", "href": "https://t.me/x/1", "body": "资料"},
    ]
    out = _format_search_results("白雪乃爱", results)
    assert "白雪乃爱 - 维基" in out
    assert "https://example.com/a" in out
    assert "介绍" in out
    assert "2. 角色主页" in out
    assert _format_search_results("x", []) == "No results found for 'x'"
