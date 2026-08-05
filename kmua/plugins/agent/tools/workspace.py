"""Agent workspace: one sandboxed agentfs instance per session.

Each session (group chat or private chat) gets its own SQLite-backed agentfs
database under `.agentfs/workspace/{session_key}.db`, so sessions can never
see each other's files. Open instances are LRU-cached with a bounded count;
evicted and shutdown paths close the underlying connections.
"""

from __future__ import annotations

import re
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

from agentfs_sdk import AgentFS, AgentFSOptions

WORKSPACE_AGENTFS_DIR = Path(".agentfs") / "workspace"
MAX_WORKSPACE_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
_SESSION_CACHE_MAX = 32

_workspace_agentfs: OrderedDict[str, AgentFS] = OrderedDict()


def _session_db_path(session_key: str) -> Path:
    return WORKSPACE_AGENTFS_DIR / f"{session_key}.db"


async def get_workspace_agentfs(session_key: str) -> AgentFS:
    """Return the workspace agentfs for *session_key*, opening it on first use.

    LRU-cached: the least recently used session is closed when the cache
    exceeds _SESSION_CACHE_MAX.
    """
    global _workspace_agentfs
    agent = _workspace_agentfs.pop(session_key, None)
    if agent is None:
        WORKSPACE_AGENTFS_DIR.mkdir(parents=True, exist_ok=True)
        agent = await AgentFS.open(
            AgentFSOptions(
                id=f"kmua-ws-{session_key}",
                path=str(_session_db_path(session_key)),
            )
        )
    _workspace_agentfs[session_key] = agent
    if len(_workspace_agentfs) > _SESSION_CACHE_MAX:
        evict_key, evicted = _workspace_agentfs.popitem(last=False)
        try:
            await evicted.close()
        except Exception:
            pass
    return agent


async def close_workspace_agentfs() -> None:
    """Close every open workspace session. Call once on bot shutdown."""
    global _workspace_agentfs
    for agent in _workspace_agentfs.values():
        try:
            await agent.close()
        except Exception:
            pass
    _workspace_agentfs.clear()


async def delete_workspace_session(session_key: str) -> None:
    """Close and delete one session's workspace database."""
    global _workspace_agentfs
    agent = _workspace_agentfs.pop(session_key, None)
    if agent is not None:
        try:
            await agent.close()
        except Exception:
            pass
    _session_db_path(session_key).unlink(missing_ok=True)


async def cleanup_stale_workspaces(max_age_days: int) -> int:
    """Delete every workspace database untouched for max_age_days; returns
    the number removed. max_age_days <= 0 sweeps everything."""
    if max_age_days < 0:
        return 0
    if not WORKSPACE_AGENTFS_DIR.exists():
        return 0
    cutoff = time.time() - max_age_days * 86400
    count = 0
    for db_path in WORKSPACE_AGENTFS_DIR.glob("*.db"):
        try:
            if db_path.stat().st_mtime >= cutoff:
                continue
        except OSError:
            continue
        await delete_workspace_session(db_path.stem)
        count += 1
    return count


def _normalize_workspace_path(path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    if ".." in Path(path).parts:
        raise ValueError(f"Path escapes the workspace: {path}")
    return path


async def write_file(session_key: str, path: str, content: str | bytes) -> None:
    """Write or overwrite a file in the session's workspace. Raises on invalid paths or oversize content."""
    agent = await get_workspace_agentfs(session_key)
    path = _normalize_workspace_path(path)
    if (
        len(content.encode("utf-8") if isinstance(content, str) else content)
        > MAX_WORKSPACE_FILE_SIZE
    ):
        raise ValueError(f"Content exceeds the {MAX_WORKSPACE_FILE_SIZE} byte limit")
    await agent.fs.write_file(path, content)


async def write_file_bytes(session_key: str, path: str, data: bytes) -> None:
    """Write raw bytes to a file in the session's workspace. Raises when oversize."""
    agent = await get_workspace_agentfs(session_key)
    path = _normalize_workspace_path(path)
    if len(data) > MAX_WORKSPACE_FILE_SIZE:
        raise ValueError(f"Content exceeds the {MAX_WORKSPACE_FILE_SIZE} byte limit")
    await agent.fs.write_file(path, data)


async def edit_file(
    session_key: str,
    path: str,
    old_text: str,
    new_text: str,
    replace_all: bool = False,
    line: int | None = None,
) -> None:
    """Replace old_text in an existing workspace file. Raises on no/multiple matches.

    When *line* is given, only that 1-indexed line is searched and edited.
    """
    agent = await get_workspace_agentfs(session_key)
    path = _normalize_workspace_path(path)
    raw = await agent.fs.read_file(path)
    content = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    if line is not None:
        lines = content.splitlines(keepends=True)
        if line < 1 or line > len(lines):
            raise ValueError(f"line {line} out of range (file has {len(lines)} lines)")
        target = lines[line - 1]
        count = target.count(old_text)
        if count == 0:
            raise ValueError(f"old_text not found on line {line}")
        if count > 1 and not replace_all:
            raise ValueError(
                f"old_text matches {count} times on line {line}; make old_text unique or pass replace_all=True"
            )
        lines[line - 1] = target.replace(old_text, new_text, -1 if replace_all else 1)
        updated = "".join(lines)
    else:
        count = content.count(old_text)
        if count == 0:
            raise ValueError(f"old_text not found in {path}")
        if count > 1 and not replace_all:
            raise ValueError(
                f"old_text matches {count} times in {path}; make old_text unique or pass replace_all=True"
            )
        updated = content.replace(old_text, new_text, -1 if replace_all else 1)
    if len(updated.encode("utf-8")) > MAX_WORKSPACE_FILE_SIZE:
        raise ValueError(f"Result exceeds the {MAX_WORKSPACE_FILE_SIZE} byte limit")
    await agent.fs.write_file(path, updated)


async def read_file(
    session_key: str, path: str, start_line: int = 1, max_lines: int = 200
) -> str | None:
    """Return a line-numbered view of a workspace file, or None if missing.

    Format identical to code_repo.read_file: a "File: {path} (lines A-B of N)"
    header, "{i:4d}: {line}" rows and "... (N lines above/below)" markers.
    """
    agent = await get_workspace_agentfs(session_key)
    path = _normalize_workspace_path(path)
    try:
        content = await agent.fs.read_file(path)
    except Exception:
        return None
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")
    lines = content.splitlines()
    start_idx = start_line - 1
    if start_idx >= len(lines):
        return None
    end_idx = min(start_idx + max_lines, len(lines))
    result = []
    if start_idx > 0:
        result.append(f"... ({start_idx} lines above)")
    for i, line in enumerate(lines[start_idx:end_idx], start=start_line):
        result.append(f"{i:4d}: {line}")
    if end_idx < len(lines):
        result.append(f"... ({len(lines) - end_idx} lines below)")
    header = f"File: {path} (lines {start_line}-{end_idx} of {len(lines)})"
    return f"{header}\n{'=' * len(header)}\n" + "\n".join(result)


async def read_file_bytes(session_key: str, path: str) -> bytes:
    """Return raw file bytes (for send). Raises when missing."""
    agent = await get_workspace_agentfs(session_key)
    path = _normalize_workspace_path(path)
    raw = await agent.fs.read_file(path)
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    return raw


async def delete_file(session_key: str, path: str) -> None:
    """Delete a file from the session's workspace. Raises when missing."""
    agent = await get_workspace_agentfs(session_key)
    path = _normalize_workspace_path(path)
    await agent.fs.unlink(path)


async def list_files(session_key: str, path: str = "/") -> list[dict[str, Any]]:
    """List workspace entries: [{name, path, is_dir, size}...] sorted dirs-first."""
    agent = await get_workspace_agentfs(session_key)
    path = _normalize_workspace_path(path)
    entries = []
    names = await agent.fs.readdir(path)
    for name in names:
        entry_path = f"{path}/{name}" if path != "/" else f"/{name}"
        try:
            stats = await agent.fs.stat(entry_path)
            entries.append(
                {
                    "name": name,
                    "path": entry_path,
                    "is_dir": stats.is_directory(),
                    "size": None if stats.is_directory() else stats.size,
                }
            )
        except Exception:
            continue
    entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
    return entries


async def search_files(
    session_key: str,
    query: str,
    path: str = "/",
    max_results: int = 20,
    use_regex: bool = False,
    case_sensitive: bool = True,
) -> list[dict[str, Any]]:
    """Recursively search a session's workspace files; returns
    [{file, matches: [{line, content}]}...]. Stops early at max_results files."""
    agent = await get_workspace_agentfs(session_key)
    path = _normalize_workspace_path(path)
    results: list[dict[str, Any]] = []
    pattern = (
        re.compile(query, flags=0 if case_sensitive else re.IGNORECASE)
        if use_regex
        else None
    )

    async def walk(dir_path: str) -> None:
        for entry in await list_files(session_key, dir_path):
            if entry["is_dir"]:
                await walk(entry["path"])
                continue
            try:
                raw = await agent.fs.read_file(entry["path"])
                text = (
                    raw.decode("utf-8", errors="replace")
                    if isinstance(raw, bytes)
                    else raw
                )
            except Exception:
                continue
            matches: list[dict[str, Any]] = []
            for i, line in enumerate(text.splitlines(), 1):
                if pattern is not None:
                    hit = pattern.search(line)
                elif case_sensitive:
                    hit = query in line
                else:
                    hit = query.lower() in line.lower()
                if hit:
                    matches.append({"line": i, "content": line.strip()[:120]})
                    if len(matches) >= 3:
                        break
            if matches:
                results.append({"file": entry["path"], "matches": matches})
                if len(results) >= max_results:
                    raise StopAsyncIteration

    try:
        await walk(path)
    except StopAsyncIteration:
        pass
    return results
