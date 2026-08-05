"""persist:// and sandbox:// protocol contracts in the unified io tools."""

from __future__ import annotations

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


def _fake_client(monkeypatch, sent=None, file_chunks=None):
    import importlib

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

    fake = FakeClient()
    client_mod = importlib.import_module("kmua.bot.client")
    monkeypatch.setattr(client_mod, "client", fake)
    return fake


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
    fake = _fake_client(monkeypatch, sent=sent)

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
    fake = _fake_client(monkeypatch, sent=sent)
    (sandbox_dir / "data.bin").write_bytes(b"\x00\x01binary")

    result = await io.write(ctx, "persist://data.bin", "sandbox://data.bin")
    assert "Persisted data.bin" in result
    assert fake.sent_kwargs is not None
    assert fake.sent_kwargs["file_name"] == "data.bin"
    assert fake.sent_kwargs["document"].getvalue() == b"\x00\x01binary"


async def test_write_persist_overwrites_same_name(ctx, monkeypatch):
    _fake_client(monkeypatch, sent=_sent_message(file_id="fid2"))
    await io.write(ctx, "persist://report.txt", "v1")
    await io.write(ctx, "persist://report.txt", "v2")
    record = await pf.get_persistent_file(-100123, "report.txt")
    assert record is not None
    assert record.file_id == "fid2"
    assert (await pf.list_persistent_files(-100123))[0].description is None


async def test_read_persist_downloads_and_pages(ctx, monkeypatch):
    _fake_client(monkeypatch, file_chunks=[b"line1\nline2\nline3"])
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
    _fake_client(monkeypatch, sent=_sent_message())
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
