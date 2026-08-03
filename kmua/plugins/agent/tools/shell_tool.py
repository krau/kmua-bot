"""Shell tool: run commands in a per-session landlock sandbox.

Files are moved in and out of the sandbox through work:// references — the
copying is done by trusted bot code, so the workspace (agentfs) keeps its
structural session isolation and the sandbox only ever sees this session's
files.
"""

from __future__ import annotations

import asyncio
import os

from pydantic_ai import RunContext
from pydantic_ai.tools import ToolDefinition

from kmua.config import app_config
from kmua.services import sandbox

from .. import datatype
from . import workspace

# The sandbox only sees work:// file basenames; deeper paths are not supported.
_MAX_IO_FILES = 10
_MAX_EXPORT_BYTES = 5 * 1024 * 1024  # matches MAX_WORKSPACE_FILE_SIZE

# Limits how many shell executions run at once across all chats/sessions
# (config: agent_shell_concurrency). Guards the shared runner and the
# container's CPU/process quota against concurrent agent turns.
_shell_semaphore: asyncio.Semaphore | None = None
_shell_semaphore_limit: int = 0


def _get_shell_semaphore() -> asyncio.Semaphore:
    global _shell_semaphore, _shell_semaphore_limit
    limit = max(1, app_config.agent_shell_concurrency)
    if _shell_semaphore is None or _shell_semaphore_limit != limit:
        _shell_semaphore = asyncio.Semaphore(limit)
        _shell_semaphore_limit = limit
    return _shell_semaphore


def _split_alias(ref: str) -> tuple[str, str | None]:
    """Split "work://a/b.txt:newname" into (work_ref, alias); alias optional."""
    path_part, _, alias = ref.rpartition(":")
    if alias and "/" not in alias and "://" in path_part:
        return path_part, alias
    return ref, None


async def _normalize_work_ref(path: str) -> str:
    """Normalize a work:// reference to a workspace path starting with '/'."""
    if not path.startswith("work://"):
        raise ValueError(f"Expected a work:// reference, got {path!r}")
    rest = "/" + path[len("work://") :].lstrip("/")
    if rest in ("", "/") or not rest.rsplit("/", 1)[-1]:
        raise ValueError(f"work:// reference has no file name: {path}")
    return rest


async def _stage_inputs(
    ctx: RunContext[datatype.ContextDeps], files: list[str]
) -> str | None:
    """Copy work:// files into the session sandbox directory. Returns error or None."""
    from . import io as io_tools

    session_key = io_tools._session_key(ctx)
    workdir = sandbox.session_shell_dir(session_key)
    workdir.mkdir(parents=True, exist_ok=True)
    for ref in files:
        work_ref, alias = _split_alias(ref)
        try:
            ws_path = await _normalize_work_ref(work_ref)
        except ValueError as e:
            return f"Error: {e}"
        try:
            data = await workspace.read_file_bytes(session_key, ws_path)
        except Exception as e:
            return f"Error: Cannot read {ref}: {e}"
        name = alias or ws_path.rsplit("/", 1)[-1]
        dest = workdir / name
        # A leftover symlink pointing outside the sandbox must not be
        # followed: unlink it first so staged input becomes a real file.
        try:
            if dest.is_symlink():
                dest.unlink()
            dest.write_bytes(data)
        except Exception as e:
            return f"Error: Cannot write {ref}: {e}"
    return None


async def _export_outputs(
    ctx: RunContext[datatype.ContextDeps], files: list[str]
) -> str | None:
    """Copy files from the session sandbox directory into work://. Error or None."""
    from . import io as io_tools

    session_key = io_tools._session_key(ctx)
    workdir = sandbox.session_shell_dir(session_key)
    for ref in files:
        work_ref, alias = _split_alias(ref)
        try:
            ws_path = await _normalize_work_ref(work_ref)
        except ValueError as e:
            return f"Error: {e}"
        name = alias or ws_path.rsplit("/", 1)[-1]
        src = workdir / name
        if src.is_symlink() or not src.exists():
            return f"Error: {name} was not produced in the sandbox."
        try:
            # O_NOFOLLOW: a symlink pointing outside the sandbox must not be
            # followed, or export would read arbitrary bot-readable files.
            fd = os.open(src, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                data = os.read(fd, _MAX_EXPORT_BYTES + 1)
            finally:
                os.close(fd)
        except OSError:
            return f"Error: {name} was not produced in the sandbox."
        if len(data) > _MAX_EXPORT_BYTES:
            return f"Error: {name} exceeds the {_MAX_EXPORT_BYTES} byte export limit."
        try:
            await workspace.write_file_bytes(session_key, ws_path, data)
        except Exception as e:
            return f"Error: Cannot write {ref}: {e}"
    return None


async def shell(
    ctx: RunContext[datatype.ContextDeps],
    command: str,
    files: list[str] = [],
    export: list[str] = [],
    timeout: int | None = None,
    clean: bool = False,
) -> str:
    """Run a shell command to compute, process or automate things.

    Use this when a task needs real execution: batch text processing,
    running scripts (python3, node), downloading and transforming data,
    checking outputs, or anything read/write/edit cannot do alone. For
    plain file editing prefer edit/write — this tool is for running code
    and shell pipelines.

    How it works:
    - Every command runs in this chat's sandbox directory. Run `pwd` to see
      it; files stay there between calls, so later commands can build on
      earlier ones.
    - Heavy or long commands are killed after a timeout; split big jobs
      into steps if you hit it.

    Args:
        command: The shell command to run (bash syntax). Consecutive calls
            share the same sandbox directory, so commands can build on each
            other's files.
        files: Copy workspace files into the sandbox before running — e.g.
            work://scripts/run.py lands as ./run.py. Append ":newname" to
            rename: work://scripts/run.py:myrun.py lands as ./myrun.py.
        export: Copy produced files back into the chat's workspace after
            running — e.g. export work://out/result.json copies ./result.json
            from the sandbox. If the sandbox file has a different name,
            append ":sourceName": export work://out/result.json:data.json
            copies ./data.json.
        timeout: Seconds to allow the command (default from config).
        clean: Start from an empty sandbox directory, removing leftovers
            from earlier calls. Use it at the start of a new task so old
            files do not confuse your commands; run `ls` if unsure what is
            in the sandbox.
    """
    from . import io as io_tools

    if len(files) > _MAX_IO_FILES or len(export) > _MAX_IO_FILES:
        return "Error: Too many files/export entries (max 10 each)."
    if not command or not command.strip():
        return "Error: command must not be empty."
    if clean:
        await sandbox.clean_session(io_tools._session_key(ctx))

    error = await _stage_inputs(ctx, files)
    if error:
        return error
    async with _get_shell_semaphore():
        result = await sandbox.run_shell(io_tools._session_key(ctx), command, timeout)
    if result.timed_out:
        return (
            f"Error: Command timed out after {timeout or app_config.agent_shell_timeout}s. "
            f"Partial output:\n{result.output}"
        )
    if result.exit_code != 0:
        return f"Command exited with code {result.exit_code}:\n{result.output}"
    error = await _export_outputs(ctx, export)
    if error:
        return error
    summary = ""
    if export:
        summary = f"\nExported {len(export)} file(s) to the workspace."
    return result.output + summary


async def prepare_shell_tools(
    ctx: RunContext[datatype.ContextDeps], tool_def: ToolDefinition
) -> ToolDefinition | None:
    """Show the shell tool only when enabled, allowed in this chat, and usable."""
    if not app_config.agent_shell_enabled:
        return None
    if not _shell_allowed_in_chat(ctx.deps.chat_id):
        return None
    if not await sandbox.landrun_available():
        return None
    return tool_def


def _shell_allowed_in_chat(chat_id: int) -> bool:
    """Only chats listed in agent_shell_allowed_chats (positive = private)."""
    return chat_id in app_config.agent_shell_allowed_chats


__all__ = ["shell", "prepare_shell_tools"]
