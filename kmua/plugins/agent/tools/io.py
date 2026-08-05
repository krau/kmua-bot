"""Unified IO tools: read/write/edit/list/search over protocol prefixes.

Protocols:
- kmua://      read-only view of the bot's own codebase (agentfs snapshot)
- work://      sandboxed workspace: files the agent writes
- chat://      the current group: info, message history, sending quotes
- memory://    the group's long-term memory
- web://       web search (DuckDuckGo)
- http(s)://   web page fetching
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

from ddgs import DDGS
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.common_tools.duckduckgo import DuckDuckGoSearchTool
from pydantic_ai.tools import ToolDefinition

from kmua.config import app_config
from kmua.logger import logger

from . import bot, chat, code_repo, datatype, db, web, workspace

_PROTOCOLS = (
    "kmua://",
    "work://",
    "chat://",
    "memory://",
    "web://",
)


def _split_target(path: str) -> tuple[str, str]:
    """Return (protocol, rest) where rest is an agentfs path starting with '/'.

    Raises ValueError for unsupported targets.
    """
    for proto in _PROTOCOLS:
        if path.startswith(proto):
            rest = path[len(proto) :]
            if not rest.startswith("/"):
                rest = "/" + rest
            return proto, rest
    if path.startswith(("http://", "https://")):
        return "http", path
    raise ValueError(
        f"Unsupported target: {path}. Use kmua:// (codebase), work:// (workspace), "
        f"chat:// (group), memory:// (memory), web:// (web search) "
        f"or http(s):// (web)."
    )


def _require(protocol: str, deps: datatype.ContextDeps) -> str | None:
    """Return an error message when a protocol is disabled, else None."""
    if protocol == "kmua://" and not app_config.agent_code_awareness:
        return "Error: Codebase access is disabled."
    if protocol == "work://" and not app_config.agent_workspace_enabled:
        return "Error: Workspace access is disabled."
    if protocol == "http" and not (
        "read" in app_config.agent_extra_tools
        or "webfetch" in app_config.agent_extra_tools
    ):
        return "Error: Web access is disabled."
    if protocol == "web://" and not (
        "search" in app_config.agent_extra_tools
        or "websearch" in app_config.agent_extra_tools
    ):
        return "Error: Web search is disabled."
    if protocol == "chat://" and deps.chat_id == deps.user_id:
        return "Error: chat:// is only available in group chats."
    if protocol == "memory://" and not deps.powermemory:
        return "Error: Group memory is not available in this chat."
    return None


def _session_key(ctx: RunContext[datatype.ContextDeps]) -> str:
    """The workspace session key: the chat id for groups, the user id for
    private chats — matching the agent session granularity. Each key owns a
    dedicated workspace database."""
    deps = ctx.deps
    return str(deps.chat_id) if deps.chat_id != deps.user_id else str(deps.user_id)


def _format_chat_info(info: db.ChatInfo) -> str:
    data = info.model_dump(exclude_none=True)
    return json.dumps(data, ensure_ascii=False, indent=2)


async def _read_chat(
    ctx: RunContext[datatype.ContextDeps], path: str, max_lines: int
) -> str:
    parts = urlsplit(path)
    if parts.path in ("", "/", "/info"):
        info = await db.get_chat_info(ctx)
        if info is None:
            return "Error: Chat info not found."
        return _format_chat_info(info)
    if parts.path == "/history":
        query = parse_qs(parts.query)
        try:
            direction = query.get("direction", ["latest"])[0]
            count = int(query.get("count", ["50"])[0])
            anchor_id = int(query["anchor_id"][0]) if query.get("anchor_id") else None
            start_id = int(query["start_id"][0]) if query.get("start_id") else None
            end_id = int(query["end_id"][0]) if query.get("end_id") else None
        except (ValueError, IndexError):
            return "Error: Invalid query parameters; expected direction/count/anchor_id/start_id/end_id integers."
        return await bot.get_history_messages(
            ctx,
            direction=direction,  # type: ignore[arg-type]
            count=count,
            anchor_id=anchor_id,
            start_id=start_id,
            end_id=end_id,
        )
    return f"Error: Unknown chat:// target {parts.path}; use /info or /history."


async def _read_content(
    ctx: RunContext[datatype.ContextDeps],
    path: str,
    start_line: int = 1,
    max_lines: int = 1500,
    raw: bool = False,
) -> str:
    """Resolve a target path to its content. Raises ValueError on failure.

    Shared by the read tool (line-numbered view) and by protocol references
    in write's content (raw=True, verbatim bytes).
    """
    protocol, rest = _split_target(path)
    denied = _require(protocol, ctx.deps)
    if denied:
        raise ValueError(denied)
    if protocol == "kmua://":
        if raw:
            agent = await code_repo.get_code_agentfs()
            if agent is None:
                raise ValueError("Code repository not initialized")
            raw_bytes = await agent.fs.read_file(rest)
            if isinstance(raw_bytes, bytes):
                return raw_bytes.decode("utf-8", errors="replace")
            return raw_bytes
        content = await code_repo.read_file(
            rest, start_line=start_line, max_lines=max_lines
        )
        if content is None:
            raise ValueError(f"File not found: {path}")
        return content
    if protocol == "work://":
        if raw:
            try:
                raw_bytes = await workspace.read_file_bytes(_session_key(ctx), rest)
            except Exception:
                raise ValueError(f"File not found: {path}") from None
            return raw_bytes.decode("utf-8", errors="replace")
        content = await workspace.read_file(
            _session_key(ctx), rest, start_line, max_lines
        )
        if content is None:
            raise ValueError(f"File not found: {path}")
        return content
    if protocol == "chat://":
        return await _read_chat(ctx, rest, max_lines)
    if protocol == "http":
        result = await web.fetch_web_page(ctx, rest)
        if not result.success:
            raise ValueError(result.error or "fetch failed")
        return result.content or ""
    raise ValueError(f"Target {path} is not readable.")


async def read(
    ctx: RunContext[datatype.ContextDeps],
    path: str,
    start_line: int = 1,
    max_lines: int = 200,
) -> str:
    """Read content from any target.

    Protocols:
    - kmua://kmua/plugins/x.py — a file from the bot's own codebase (read-only)
    - work://notes/hello.html — a file from this chat's workspace
    - chat://info             — information about the current group
    - chat://history?direction=latest|before|after|between&count=N&anchor_id=N&start_id=N&end_id=N
                              — messages from the current group
    - https://example.com     — a web page as markdown/text

    Use start_line/max_lines to page through kmua:// and work:// targets
    (1-indexed; max_lines up to 1500).
    """
    if max_lines < 1 or max_lines > 1500:
        raise ModelRetry("max_lines must be between 1 and 1500")
    if start_line < 1:
        raise ModelRetry("start_line must be >= 1")
    try:
        return await _read_content(ctx, path, start_line, max_lines)
    except Exception as e:
        logger.error(f"read error for {path}: {e}")
        return f"Error: {e}"


async def write(
    ctx: RunContext[datatype.ContextDeps],
    path: str,
    content: str | None = None,
) -> str:
    """Write content to a target. The path is the destination; content is the payload.

    Protocols:
    - work://notes/hello.html — save content as a file in the chat's workspace
    - memory://               — store content as a fact about this group in its
        long-term memory

    content can be plain text or a reference to another target whose content
    is used as the payload — e.g. work://notes/hello.html (workspace file) or
    kmua://kmua/services/wechat.py (codebase file, read-only), handy for
    copying files between targets.

    Files in the workspace are sandboxed. Large content (over 5 MB) is rejected.
    Prefer edit when modifying an existing workspace file.
    """
    try:
        protocol, rest = _split_target(path)
    except ValueError as e:
        return f"Error: {e}"
    denied = _require(protocol, ctx.deps)
    if denied:
        return denied
    if content is not None:
        try:
            _split_target(content)
        except ValueError:
            pass  # plain text
        else:
            # Protocol reference: resolve the referenced content as the payload.
            # Non-readable protocols (memory://, web://) are rejected by
            # _read_content.
            try:
                content = await _read_content(ctx, content, raw=True)
            except Exception as e:
                logger.error(f"write error for {path}: resolving {content}: {e}")
                return f"Error: {e}"
    try:
        if protocol == "memory://":
            if content is None:
                return "Error: content is required for memory:// targets."
            return await chat.update_group_memory(ctx, content)
        if protocol != "work://":
            return f"Error: {path} is read-only or not writable; only work:// and memory:// targets accept writes."
        if content is None:
            return "Error: content is required for work:// targets."
        await workspace.write_file(_session_key(ctx), rest, content)
    except Exception as e:
        logger.error(f"write error for {path}: {e}")
        return f"Error: {e}"
    return (
        f"Wrote {len(content.encode('utf-8'))} bytes to {path}. "
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
    to make old_text unique — the edit is refused when it matches nothing or
    matches multiple places (pass replace_all=True only when you really want
    every occurrence changed). Pass line (1-indexed) to restrict the edit to a
    single line, which is handy for long files.
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
    - work://subdir       — workspace subdirectory
    - kmua://kmua/plugins — a codebase directory (read-only)
    """
    try:
        protocol, rest = _split_target(path)
    except ValueError as e:
        return f"Error: {e}"
    denied = _require(protocol, ctx.deps)
    if denied:
        return denied
    try:
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


async def _search_web(query: str, max_results: int) -> str:
    results = await DuckDuckGoSearchTool(
        DDGS(), max_results=min(max_results, 10)
    ).__call__(query)
    if not results:
        return f"No results found for '{query}'"
    lines = [f"Search results for '{query}' ({len(results)}):"]
    for i, r in enumerate(results, 1):
        title = getattr(r, "title", None) or ""
        url = getattr(r, "url", None) or ""
        snippet = getattr(r, "snippet", None) or ""
        lines.append(f"\n{i}. {title}\n   {url}\n   {snippet}")
    return "\n".join(lines)


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
    - kmua://           — the bot's own codebase
    - work://           — the agent workspace
    - web://            — web search (DuckDuckGo)
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
    """Delete a file from the chat's workspace (work:// only).

    The file is removed permanently from this session's workspace. Deleting
    codebase files (kmua://) or any other target is not allowed.
    """
    try:
        protocol, rest = _split_target(path)
    except ValueError as e:
        return f"Error: {e}"
    if protocol != "work://":
        return f"Error: {path} is not deletable; only work:// targets can be deleted."
    denied = _require(protocol, ctx.deps)
    if denied:
        return denied
    try:
        await workspace.delete_file(_session_key(ctx), rest)
    except Exception as e:
        logger.error(f"delete error for {path}: {e}")
        return f"Error: {e}"
    return f"Deleted {path}."


async def prepare_io_tools(
    ctx: RunContext[datatype.ContextDeps], tool_def: ToolDefinition
) -> ToolDefinition | None:
    """Show IO tools when any protocol source is enabled.

    In private chats, group-only protocols (chat://, memory://) are stripped
    from the tool description so the model does not attempt them.
    """
    if not (
        app_config.agent_code_awareness
        or app_config.agent_workspace_enabled
        or "search" in app_config.agent_extra_tools
        or "websearch" in app_config.agent_extra_tools
    ):
        return None
    if ctx.deps.chat_id == ctx.deps.user_id and tool_def.description:
        lines = [
            ln
            for ln in tool_def.description.splitlines()
            if "chat://" not in ln and "memory://" not in ln
        ]
        trimmed = "\n".join(lines).strip()
        if trimmed != tool_def.description.strip():
            tool_def.description = trimmed
    return tool_def


__all__ = ["read", "write", "edit", "list", "search", "delete", "prepare_io_tools"]
