"""The six IO tool functions exposed to the model."""

from __future__ import annotations

import builtins
from typing import Any

from ddgs import DDGS
from pydantic_ai import ModelRetry, RunContext, ToolReturn
from pydantic_ai.common_tools.duckduckgo import DuckDuckGoSearchTool

from kmua.logger import logger

from .. import bot, chat, code_repo, datatype, workspace
from .content import _read_content
from .media import _native_image_return, _tme_message_parts
from .protocols import _require, _split_target
from .targets import _sandbox_target, _session_key, _write_persisted, read_bytes


async def read(
    ctx: RunContext[datatype.ContextDeps],
    path: str,
    start_line: int = 1,
    max_lines: int = 200,
) -> str | ToolReturn:
    """Read content from any target.

    Protocols:
    - kmua://kmua/plugins/x.py — a file from the kmua's own codebase
    - work://notes/hello.html — a file from this chat's workspace
    - persist://report.txt    — a file the agent persisted for this chat
    - chat://media/123        — the media of message 123 in this chat
    - https://t.me/MoreACG/27411 — a public t.me message.
    - chat://info             — information about the current group
- chat://history?direction=latest|before|after|between&count=N&anchor_id=N&start_id=N&end_id=N
    - https://example.com     — a web page as text

    Use start_line/max_lines to page through kmua://, work://, persist://
    and t.me targets (1-indexed; max_lines up to 1500).
    """
    if max_lines < 1 or max_lines > 1500:
        raise ModelRetry("max_lines must be between 1 and 1500")
    if start_line < 1:
        raise ModelRetry("start_line must be >= 1")
    try:
        protocol, _ = _split_target(path)
    except ValueError:
        protocol = ""
    is_media_target = (protocol == "chat://" and "/media/" in path) or (
        protocol == "http" and _tme_message_parts(path) is not None
    )
    if is_media_target:
        try:
            native = await _native_image_return(ctx, path, path)
        except Exception as e:
            logger.error(f"read error for {path}: {e}")
            return f"Error: {e}"
        if native is not None:
            return native
    try:
        return await _read_content(ctx, path, start_line, max_lines)
    except Exception as e:
        logger.error(f"read error for {path}: {e}")
        return f"Error: {e}"


async def write(
    ctx: RunContext[datatype.ContextDeps],
    path: str,
    content: str | bytes | None = None,
) -> str:
    """Write content to a target. The path is the destination; content is the payload.

    Protocols:
    - work://notes/hello.html — save content as a file in the chat's workspace
    - persist://report.txt    — persist a file for this chat: it is sent as a
        document to the chat and recorded; later runs can read, list, delete
        and overwrite it by name.
    - memory://               — store content as a fact about this group in its
        long-term memory

    content can be plain text or a reference to another target whose content
    is used as the payload — e.g. work://notes/hello.html (workspace file) or
    kmua://kmua/services/wechat.py (codebase file), handy for
    copying files between targets. A chat://media/<message_id> reference
    downloads a message's media from this chat, and an https://t.me/... link
    from a public Telegram chat. Binary payloads must go
    through a reference (work://, persist://, chat://media, a t.me link).

    Keep content under 5 MB. Prefer edit when modifying an existing
    workspace file.
    """
    try:
        protocol, rest = _split_target(path)
    except ValueError as e:
        return f"Error: {e}"
    denied = _require(protocol, ctx.deps)
    if denied:
        return denied
    if isinstance(content, str):
        try:
            _split_target(content)
        except ValueError:
            pass  # plain text
        else:
            # Protocol reference: resolve the referenced content as raw bytes
            # (lossless for binary payloads; text round-tripping would
            # corrupt non-UTF-8 bytes).
            try:
                content = await read_bytes(content, ctx)
            except Exception as e:
                logger.error(f"write error for {path}: resolving {content}: {e}")
                return f"Error: {e}"
    if content is None:
        return f"Error: content is required for {path} targets."
    try:
        if protocol == "memory://":
            text = content if isinstance(content, str) else content.decode("utf-8")
            return await chat.update_group_memory(ctx, text)
        if protocol == "persist://":
            return await _write_persisted(ctx, rest, content)
        if protocol == "sandbox://":
            target = _sandbox_target(_session_key(ctx), rest)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(
                content.encode("utf-8") if isinstance(content, str) else content
            )
            return f"Wrote {len(content) if isinstance(content, bytes) else len(content.encode('utf-8'))} bytes to {path}."
        if protocol != "work://":
            return f"Error: {path} is read-only or not writable; only work://, sandbox://, persist:// and memory:// targets accept writes."
        await workspace.write_file(_session_key(ctx), rest, content)
    except Exception as e:
        logger.error(f"write error for {path}: {e}")
        return f"Error: {e}"
    size = len(content) if isinstance(content, bytes) else len(content.encode("utf-8"))
    return (
        f"Wrote {size} bytes to {path}. "
        f"Use read to verify, or tg sendDocument to share it."
    )


async def edit(
    ctx: RunContext[datatype.ContextDeps],
    path: str,
    old_text: str,
    new_text: str,
    replace_all: bool = False,
    line: int | None = None,
) -> str:
    """Edit a file in the chat's workspace (work:// only).

    Replaces old_text with new_text in the file. Give enough surrounding text
    to make old_text unique. Pass replace_all=True to change every occurrence.
    Pass line (1-indexed) to restrict the edit to a single line, handy for
    long files.
    """
    try:
        protocol, rest = _split_target(path)
    except ValueError as e:
        return f"Error: {e}"
    if protocol != "work://":
        return f"Error: {path} is read-only or not editable; only work:// targets accept edits."
    denied = _require(protocol, ctx.deps)
    if denied:
        return denied
    try:
        await workspace.edit_file(
            _session_key(ctx), rest, old_text, new_text, replace_all, line
        )
    except Exception as e:
        logger.error(f"edit error for {path}: {e}")
        return f"Error: {e}"
    return f"Edited {path}. Use read to verify."


async def list(ctx: RunContext[datatype.ContextDeps], path: str = "work://") -> str:
    """List files and directories.

    Protocols:
    - work://             — agent workspace (default)
    - persist://          — files persisted for this chat
    - kmua://             — kmua's codebase
    """
    try:
        protocol, rest = _split_target(path)
    except ValueError as e:
        return f"Error: {e}"
    denied = _require(protocol, ctx.deps)
    if denied:
        return denied
    try:
        if protocol == "persist://":
            from kmua.database import persistent_file as pf_db

            files = await pf_db.list_persistent_files(ctx.deps.chat_id)
            _ = rest
            if not files:
                return "No persisted files for this chat."
            lines = ["name | size | updated"]
            for f in files:
                kb = (f.file_size or 0) / 1024
                lines.append(f"{f.name} | {kb:.1f} KB | {f.updated_at:%Y-%m-%d %H:%M}")
            return "\n".join(lines)
        if protocol == "sandbox://":
            root = _sandbox_target(_session_key(ctx), rest)
            if not root.exists():
                return f"Path not found: {path}"
            lines = ["name | size | type"]
            for item in sorted(root.iterdir(), key=lambda p: p.name):
                kind = "dir" if item.is_dir() else str(item.stat().st_size)
                lines.append(f"{item.name} | {kind}")
            return "\n".join(lines)
        if protocol == "kmua://":
            entries = await code_repo.list_files(rest, include_dirs=True)
            if not entries:
                return f"Path not found: {path}"
            lines = ["name | size | type"]
            for e in entries:
                kind = "dir" if e.get("is_dir") else str(e.get("size", "?"))
                lines.append(f"{e.get('name', '?')} | {kind}")
            return "\n".join(lines)
        entries = await workspace.list_files(_session_key(ctx), rest)
        if not entries:
            return f"Workspace is empty at {path}."
        lines = ["name | size | type"]
        for e in entries:
            kind = "dir" if e["is_dir"] else str(e["size"])
            lines.append(f"{e['name']} | {kind}")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"list error for {path}: {e}")
        return f"Error: {e}"


def _format_search_results(query: str, results: builtins.list[Any]) -> str:
    """Render search results; results are dicts with title/href/body keys."""
    if not results:
        return f"No results found for '{query}'"
    lines = [f"Search results for '{query}' ({len(results)}):"]
    for i, r in enumerate(results, 1):
        title = r.get("title") or ""
        url = r.get("href") or ""
        snippet = r.get("body") or ""
        lines.append(f"\n{i}. {title}\n   {url}\n   {snippet}")
    return "\n".join(lines)


async def _search_web(query: str, max_results: int) -> str:
    results = await DuckDuckGoSearchTool(
        DDGS(), max_results=min(max_results, 10)
    ).__call__(query)
    return _format_search_results(query, results)


async def search(
    ctx: RunContext[datatype.ContextDeps],
    query: str,
    path: str = "kmua://",
    max_results: int = 20,
    use_regex: bool = False,
    case_sensitive: bool = True,
) -> str:
    """Search text across files, web, chat messages or group memory.

    Protocols:
    - kmua://           — the kmua's own codebase
    - work://           — the agent workspace
    - web://            — search on Internet
    - chat://           — messages in the current group
    - memory://         — the group's long-term memory (semantic search)

    query must be at least 2 characters; max_results 1-50.
    """
    if not query or len(query) < 2:
        raise ModelRetry("Query must be at least 2 characters")
    if max_results < 1 or max_results > 50:
        raise ModelRetry("max_results must be between 1 and 50")
    try:
        protocol, rest = _split_target(path)
    except ValueError as e:
        return f"Error: {e}"
    denied = _require(protocol, ctx.deps)
    if denied:
        return denied
    try:
        if protocol == "kmua://":
            results = await code_repo.search_in_files(
                query,
                max_results=max_results,
                use_regex=use_regex,
                case_sensitive=case_sensitive,
            )
            if not results:
                return f"No results found for '{query}'"
            parts = [f"Search results for '{query}' ({len(results)} files):"]
            for i, r in enumerate(results, 1):
                parts.append(
                    f"\n{i}. {r.get('file', 'unknown')} ({r.get('total_matches', 0)} matches)"
                )
                for m in r.get("matches", [])[:3]:
                    parts.append(f"   Line {m.get('line', 0)}: {m.get('content', '')}")
            return "\n".join(parts)
        if protocol == "work://":
            results = await workspace.search_files(
                _session_key(ctx),
                query,
                path=rest,
                max_results=max_results,
                use_regex=use_regex,
                case_sensitive=case_sensitive,
            )
            if not results:
                return f"No results found for '{query}'"
            parts = [f"Search results for '{query}' ({len(results)} files):"]
            for i, r in enumerate(results, 1):
                parts.append(f"\n{i}. {r['file']} ({len(r['matches'])} matches shown)")
                for m in r["matches"]:
                    parts.append(f"   Line {m['line']}: {m['content']}")
            return "\n".join(parts)
        if protocol == "web://":
            return await _search_web(query, max_results)
        if protocol == "chat://":
            return await bot.search_messages(ctx, query, count=max_results)
        memories = await chat.search_group_memory(ctx, query)
        if not memories:
            return "No memories found."
        return "\n".join(f"- {m}" for m in memories)
    except Exception as e:
        logger.error(f"search error: {e}")
        return f"Error: {e}"


async def delete(
    ctx: RunContext[datatype.ContextDeps],
    path: str,
) -> str:
    """Delete a file from the workspace or the persisted set.

    work:// removes the local file. persist:// delete the record.
    """
    try:
        protocol, rest = _split_target(path)
    except ValueError as e:
        return f"Error: {e}"
    denied = _require(protocol, ctx.deps)
    if denied:
        return denied
    try:
        if protocol == "persist://":
            from kmua.database import persistent_file as pf_db

            name = rest.lstrip("/")
            deleted = await pf_db.delete_persistent_file(ctx.deps.chat_id, name)
            if not deleted:
                return f"Error: No persisted file named {name!r} in this chat."
            return f"Removed {name} from the managed set; the chat message stays."
        if protocol == "sandbox://":
            target = _sandbox_target(_session_key(ctx), rest)
            target.unlink(missing_ok=True)
            return f"Deleted {path}."
        if protocol != "work://":
            return f"Error: {path} is not deletable; only work://, sandbox:// and persist:// targets can be deleted."
        await workspace.delete_file(_session_key(ctx), rest)
    except Exception as e:
        logger.error(f"delete error for {path}: {e}")
        return f"Error: {e}"
    return f"Deleted {path}."
