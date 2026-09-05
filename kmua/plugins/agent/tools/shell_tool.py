"""Shell tool: run commands in a per-session landlock sandbox.

The sandbox is a real per-session directory; io tools address it as
sandbox:// (read/write/list/delete), so produced files move to the workspace
with an ordinary protocol copy. The workspace (agentfs) keeps its structural
session isolation; the sandbox only ever sees this session's files.
"""

from __future__ import annotations

import asyncio

from pydantic_ai import RunContext
from pydantic_ai.tools import ToolDefinition

from kmua.config import app_config
from kmua.services import sandbox

from .. import datatype
from . import workspace

# The sandbox only sees work:// file basenames; deeper paths are not supported.
_MAX_IO_FILES = 10

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


async def shell(
    ctx: RunContext[datatype.ContextDeps],
    command: str,
    files: list[str] = [],
    timeout: int | None = None,
    clean: bool = False,
) -> str:
    """Run a bash command in this chat's sandbox.

    Commands share the same sandbox directory across calls,
    so later commands can build on earlier ones. Anywhere
    that accepts a work:// reference (io tools, tg media fields) also
    accepts sandbox:// for a file in this sandbox, e.g.
    `write work://out/result.json content="sandbox://result.json"` copies a
    produced file out.

    For Python packages: `python3 -m pip install --target="$PWD/pylibs" <pkg>`
    then run with `PYTHONPATH="$PWD/pylibs"` (session-only).

    Args:
        command: The bash command to run.
        files: Copy workspace files into the sandbox first, e.g.
            work://scripts/run.py lands as ./run.py; append ":newname" to
            rename.
        timeout: Seconds to allow the command (default from config).
        clean: Start from an empty sandbox directory, removing leftovers
            from earlier calls.
    """
    from . import io as io_tools

    if len(files) > _MAX_IO_FILES:
        return "Error: Too many files entries (max 10)."
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
    return result.output


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
