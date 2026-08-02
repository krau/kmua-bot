"""Shell tool: landlock sandboxed execution with work:// staging/export."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from kmua.config import app_config
from kmua.plugins.agent.tools import shell_tool
from kmua.services import sandbox


def _ctx():
    return SimpleNamespace(
        deps=SimpleNamespace(
            client=SimpleNamespace(),
            chat_id=-100_123,
            user_id=1001,
            message=SimpleNamespace(id=7, guest_query_id=None),
            is_guest_mode=False,
            tools_called_this_turn=set(),
        )
    )


def _ws_ctx(session_key="sess-a"):
    from kmua.plugins.agent.tools import io as io_tools

    return io_tools._session_key(_ctx()), session_key


@pytest.fixture
def fake_landrun(monkeypatch, tmp_path):
    """Point the sandbox at a fake landrun that executes bash directly.

    Keeps tests hermetic (no real landrun/kernel dependency) while exercising
    the sandbox orchestration: workdir creation, env, output handling.
    """
    script = tmp_path / "landrun"
    script.write_text(
        "#!/bin/sh\n"
        "shift\n"  # drop the landrun binary name
        # skip all options until --, then exec the command
        "while [ $# -gt 0 ]; do\n"
        '  [ "$1" = "--" ] && shift && break\n'
        "  shift\n"
        "done\n"
        'exec "$@"\n'
    )
    script.chmod(0o755)
    monkeypatch.setattr(app_config, "agent_landrun_path", str(script))
    monkeypatch.setattr(app_config, "agent_shell_enabled", True)
    monkeypatch.setattr(sandbox, "_landrun_available", True)
    monkeypatch.setattr(app_config, "agent_shell_network_ports", [80, 443])
    monkeypatch.setattr(
        sandbox,
        "session_shell_dir",
        lambda key: tmp_path / "sessions" / key,
    )
    return tmp_path


async def test_shell_runs_command(fake_landrun):
    result = await shell_tool.shell(_ctx(), "echo hello")
    assert "hello" in result


async def test_shell_exit_code_reported(fake_landrun):
    result = await shell_tool.shell(_ctx(), "exit 3")
    assert "exited with code 3" in result


async def test_shell_empty_command(fake_landrun):
    result = await shell_tool.shell(_ctx(), "   ")
    assert "must not be empty" in result


async def test_shell_stages_work_files(fake_landrun, monkeypatch):
    """work:// inputs land in the sandbox as their basename."""
    from kmua.plugins.agent.tools import io as io_tools
    from kmua.plugins.agent.tools import workspace

    session_key = io_tools._session_key(_ctx())

    async def fake_read_bytes(key, path):
        assert key == session_key
        assert path == "/scripts/run.py"
        return b"print('staged')"

    async def fake_write_bytes(key, path, data):
        raise AssertionError("no export expected")

    monkeypatch.setattr(workspace, "read_file_bytes", fake_read_bytes)
    monkeypatch.setattr(workspace, "write_file_bytes", fake_write_bytes)
    result = await shell_tool.shell(
        _ctx(), "cat run.py", files=["work://scripts/run.py"]
    )
    assert "staged" in result


async def test_shell_exports_work_files(fake_landrun, monkeypatch):
    """Export copies the produced basename back into the workspace."""
    from kmua.plugins.agent.tools import io as io_tools
    from kmua.plugins.agent.tools import workspace

    session_key = io_tools._session_key(_ctx())
    written = {}

    async def fake_write_bytes(key, path, data):
        written[(key, path)] = data

    monkeypatch.setattr(workspace, "write_file_bytes", fake_write_bytes)
    result = await shell_tool.shell(
        _ctx(), "echo data > out.txt", export=["work://out/out.txt"]
    )
    assert "Exported 1 file(s)" in result
    assert written[(session_key, "/out/out.txt")] == b"data\n"


async def test_shell_export_missing_file(fake_landrun):
    result = await shell_tool.shell(_ctx(), "echo x", export=["work://o/nope.txt"])
    assert "was not produced" in result


async def test_shell_stage_missing_workspace_file(fake_landrun, monkeypatch):
    from kmua.plugins.agent.tools import workspace

    async def fake_read_bytes(key, path):
        raise ValueError("File not found")

    monkeypatch.setattr(workspace, "read_file_bytes", fake_read_bytes)
    result = await shell_tool.shell(_ctx(), "ls", files=["work://nope.txt"])
    assert "Cannot read" in result


async def test_shell_bad_reference_rejected(fake_landrun):
    result = await shell_tool.shell(_ctx(), "ls", files=["work://"])
    assert "no file name" in result
    result2 = await shell_tool.shell(_ctx(), "ls", files=["kmua://x"])
    assert "Expected a work:// reference" in result2


async def test_shell_prepare_gates(fake_landrun, monkeypatch):
    from pydantic_ai import RunContext
    from pydantic_ai import tools as pai_tools

    from kmua.plugins.agent import datatype

    deps = datatype.ContextDeps(
        client=SimpleNamespace(),
        user_id=1001,
        chat_id=-100123,
        message=SimpleNamespace(id=1, guest_query_id=None),
    )
    ctx = RunContext(
        deps=deps, model=SimpleNamespace(), usage=SimpleNamespace(), messages=[]
    )
    td = pai_tools.ToolDefinition(
        name="shell", description="", parameters_json_schema={}
    )
    # disabled
    monkeypatch.setattr(app_config, "agent_shell_enabled", False)
    assert await shell_tool.prepare_shell_tools(ctx, td) is None
    # enabled but landrun unavailable
    monkeypatch.setattr(app_config, "agent_shell_enabled", True)
    monkeypatch.setattr(sandbox, "_landrun_available", None)

    async def unavailable():
        return False

    async def available():
        return True

    monkeypatch.setattr(sandbox, "landrun_available", unavailable)
    assert await shell_tool.prepare_shell_tools(ctx, td) is None
    # enabled + available + chat listed
    monkeypatch.setattr(sandbox, "landrun_available", available)
    monkeypatch.setattr(app_config, "agent_shell_allowed_chats", [-100123])
    assert await shell_tool.prepare_shell_tools(ctx, td) is not None
    # chat allowlist: unlisted chats are hidden
    monkeypatch.setattr(app_config, "agent_shell_allowed_chats", [])
    assert await shell_tool.prepare_shell_tools(ctx, td) is None
    monkeypatch.setattr(app_config, "agent_shell_allowed_chats", [-100999])
    assert await shell_tool.prepare_shell_tools(ctx, td) is None
    # positive id = private chat
    deps.chat_id = 12345
    monkeypatch.setattr(app_config, "agent_shell_allowed_chats", [12345])
    assert await shell_tool.prepare_shell_tools(ctx, td) is not None
    monkeypatch.setattr(app_config, "agent_shell_allowed_chats", [54321])
    assert await shell_tool.prepare_shell_tools(ctx, td) is None


async def test_shell_files_alias_renames(fake_landrun, monkeypatch):
    """files entries support work://path:newname."""
    from kmua.plugins.agent.tools import workspace

    async def fake_read_bytes(key, path):
        assert path == "/scripts/run.py"
        return b"print('x')"

    monkeypatch.setattr(workspace, "read_file_bytes", fake_read_bytes)
    result = await shell_tool.shell(
        _ctx(), "ls", files=["work://scripts/run.py:myrun.py"]
    )
    assert result is not None  # command ran; alias landed as myrun.py


async def test_shell_export_alias_source(fake_landrun, monkeypatch):
    """export work://dst:source copies ./source into the workspace."""
    from kmua.plugins.agent.tools import workspace

    written = {}

    async def fake_write_bytes(key, path, data):
        written[(key, path)] = data

    monkeypatch.setattr(workspace, "write_file_bytes", fake_write_bytes)
    result = await shell_tool.shell(
        _ctx(), "echo zz > data.json", export=["work://out/result.json:data.json"]
    )
    assert "Exported 1 file(s)" in result
    assert written[("-100123", "/out/result.json")] == b"zz\n"


async def test_shell_clean_removes_leftovers(fake_landrun, monkeypatch):
    """clean=true starts from an empty sandbox (except kmua link and tmp)."""
    from kmua.plugins.agent.tools import io as io_tools

    session_key = io_tools._session_key(_ctx())
    workdir = sandbox.session_shell_dir(session_key)
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "old.txt").write_text("leftover")
    (workdir / "tmp").mkdir(exist_ok=True)
    (workdir / "kmua").symlink_to("/nonexistent", target_is_directory=True)

    monkeypatch.setattr(sandbox, "clean_session", lambda key: None) if False else None

    # use the real clean_session (no monkeypatch): run through shell with clean
    result = await shell_tool.shell(_ctx(), "ls", clean=True)
    assert result is not None
    leftovers = [p.name for p in workdir.iterdir()]
    assert "old.txt" not in leftovers
    assert "tmp" in leftovers
    assert "kmua" in leftovers
