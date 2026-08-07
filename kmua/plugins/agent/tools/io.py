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

import asyncio
import builtins
import json
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from ddgs import DDGS
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.common_tools.duckduckgo import DuckDuckGoSearchTool
from pydantic_ai.tools import ToolDefinition

from kmua.common.safe_http import UnsafeUrlError, safe_download_bytes
from kmua.config import app_config
from kmua.logger import logger

from . import bot, chat, code_repo, datatype, db, web, workspace

_PROTOCOLS = (
    "kmua://",
    "work://",
    "sandbox://",
    "persist://",
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
        f"Unsupported target: {path}. Use kmua:// (codebase), work:// "
        f"(workspace), persist:// (persisted files), chat:// (current chat: "
        f"info, history, media), memory:// (memory), web:// (web search) or "
        f"http(s):// (web; t.me message links download the media)."
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


def _safe_sandbox_path(rel: str) -> Path:
    """Resolve a sandbox-relative path, rejecting escapes."""
    p = Path(rel.lstrip("/"))
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"Path escapes the sandbox: {rel}")
    return p


def _sandbox_target(session_key: str, rel: str) -> Path:
    """The real path for a sandbox:// target, refusing symlink traversal.

    Sandbox commands may create symlinks pointing outside the sandbox;
    following one would let the io tools read or write arbitrary
    bot-readable files. Every path component must be a real directory or
    file, never a symlink.
    """
    from kmua.services import sandbox

    root = sandbox.session_shell_dir(session_key)
    rel_path = _safe_sandbox_path(rel)
    probe = root
    for part in rel_path.parts:
        probe = probe / part
        if probe.is_symlink():
            raise ValueError(f"sandbox:// paths must not use symlinks: {rel}")
    return root / rel_path


async def read_bytes(path: str, ctx: RunContext[datatype.ContextDeps]) -> bytes:
    """Read a target as raw bytes (persist payloads and binary copies)."""
    protocol, rest = _split_target(path)
    denied = _require(protocol, ctx.deps)
    if denied:
        raise ValueError(denied)
    if protocol == "work://":
        return await workspace.read_file_bytes(_session_key(ctx), rest)
    if protocol == "sandbox://":
        target = _sandbox_target(_session_key(ctx), rest)
        return target.read_bytes()
    if protocol == "kmua://":
        agent = await code_repo.get_code_agentfs()
        if agent is None:
            raise ValueError("Code repository not initialized")
        raw = await agent.fs.read_file(rest)
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        return raw
    if protocol == "persist://":
        return await _download_persisted(ctx, rest)
    if protocol == "chat://" and rest.startswith("/media/"):
        return await _download_chat_media(ctx, rest)
    if protocol == "http":
        if urlsplit(rest).hostname in ("t.me", "telegram.me"):
            # Telegram media is downloaded through the bot client, not the
            # plain HTTP path (t.me pages are HTML, the files live in MTProto).
            return await _download_tme_media(ctx, rest)
        try:
            return await safe_download_bytes(
                rest, max_bytes=app_config.agent_download_max_bytes
            )
        except (UnsafeUrlError, Exception) as e:
            raise ValueError(f"Download failed: {e}") from None
    raise ValueError(f"Target {path} is not readable.")


async def _read_sandbox_lines(
    ctx: RunContext[datatype.ContextDeps],
    rel: str,
    start_line: int,
    max_lines: int,
) -> str | None:
    """Line-numbered view of a sandbox file (None when missing)."""
    try:
        target = _sandbox_target(_session_key(ctx), rel)
        text = target.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return None
    lines = text.splitlines()
    selected = lines[start_line - 1 : start_line - 1 + max_lines]
    return "\n".join(selected)


async def _write_persisted(
    ctx: RunContext[datatype.ContextDeps], name: str, content: str | bytes
) -> str:
    """Persist a file: send it to the chat as a document and record it.

    content may be plain text or a protocol reference (work://, kmua://,
    persist://) whose bytes are persisted; binary payloads go through
    references so they are not round-tripped through text.
    """
    name = name.lstrip("/")
    if not name or "/" in name or len(name) > 256:
        return "Error: name must be a plain name of 1-256 characters."
    data = content.encode("utf-8") if isinstance(content, str) else content
    if not data:
        return "Error: The content is empty."
    if len(data) > workspace.MAX_WORKSPACE_FILE_SIZE:
        return (
            f"Error: File exceeds the {workspace.MAX_WORKSPACE_FILE_SIZE} byte limit."
        )
    client = ctx.deps.client

    try:
        sent = await client.send_document(
            ctx.deps.chat_id,
            document=BytesIO(data),
            file_name=name,
            caption=name,
        )
    except Exception as e:
        logger.error(f"persist write failed for {name!r}: {e}")
        return "Error: Failed to send the file to this chat."
    assert sent is not None, "send_document returned None"
    assert sent.document is not None, "sent message has no document"
    doc = sent.document
    from kmua.database import persistent_file as pf_db

    try:
        await pf_db.upsert_persistent_file(
            chat_id=ctx.deps.chat_id,
            name=name,
            description=None,
            tg_message_id=sent.id,
            file_id=doc.file_id,
            file_unique_id=doc.file_unique_id,
            file_name=doc.file_name,
            mime_type=doc.mime_type,
            file_size=doc.file_size,
        )
    except Exception as e:
        # The document was already sent; a failed record would leave an
        # orphan file in chat history, so remove it again.
        logger.error(f"persist record failed for {name!r}: {e}")
        try:
            await client.delete_messages(ctx.deps.chat_id, sent.id)
        except Exception:
            pass
        return "Error: Failed to record the file; the sent document was removed."
    logger.info(
        f"agent persisted file {name!r} to chat {ctx.deps.chat_id} (message {sent.id})"
    )
    return f"Persisted {name} for this chat (sent as a document)."


async def _download_persisted(
    ctx: RunContext[datatype.ContextDeps], name: str
) -> bytes:
    """Download a persisted file's bytes from chat history."""
    from kmua.database import persistent_file as pf_db

    name = name.lstrip("/")
    record = await pf_db.get_persistent_file(ctx.deps.chat_id, name)
    if record is None:
        raise ValueError(f"No persisted file named {name!r} in this chat.")
    from pyrogram.file_id import FileId

    timeout = app_config.agent_download_timeout or None

    async def _collect():
        file_id = FileId.decode(record.file_id)
        if file_id is None:
            raise ValueError("The stored file id is invalid.")
        chunks = [chunk async for chunk in ctx.deps.client.get_file(file_id)]
        return b"".join(chunks)

    return await asyncio.wait_for(_collect(), timeout=timeout)


class _NoMediaError(ValueError):
    """The message has no downloadable media (lets read fall back to the
    web text extraction for plain-text t.me posts)."""


def _tg_media_size(message: Any) -> int | None:
    """The byte size of a message's media, whichever type it is."""
    for attr in (
        "photo",
        "video",
        "audio",
        "voice",
        "document",
        "sticker",
        "animation",
        "video_note",
    ):
        media = getattr(message, attr, None)
        if media is not None and getattr(media, "file_size", None):
            return media.file_size
    return None


async def _download_tg_bytes(client: Any, message: Any, what: str) -> bytes:
    """Download one message's media with the configured timeout and cap.

    Paid media and albums are refused before any download; the declared
    size is pre-checked and the actual bytes are counted as a second layer.
    """
    if getattr(message, "paid_media", None):
        raise ValueError(f"{what}: paid media is not supported.")
    size = _tg_media_size(message)
    if size is None:
        # A truthy message.media is not enough: web-page previews count as
        # media but carry no downloadable file. read falls back to the web
        # text extraction for these.
        raise _NoMediaError(f"{what}: the message has no downloadable media.")
    max_bytes = app_config.agent_download_max_bytes
    if size > max_bytes:
        raise ValueError(
            f"{what}: the file is {size} bytes, over the {max_bytes} "
            f"byte download limit."
        )
    timeout = app_config.agent_download_timeout or None
    media = await asyncio.wait_for(
        client.download_media(message, in_memory=True), timeout=timeout
    )
    if isinstance(media, builtins.list):
        raise ValueError(
            f"{what}: the message contains an album of several media files; "
            f"albums are not supported."
        )
    if not isinstance(media, BytesIO):
        raise ValueError(f"Failed to download {what}.")
    data = media.getvalue()
    if len(data) > max_bytes:
        raise ValueError(
            f"{what}: the file is over the {max_bytes} byte download limit."
        )
    return data


async def _download_chat_media(
    ctx: RunContext[datatype.ContextDeps], rest: str
) -> bytes:
    """Download the media of a message in the current chat
    (chat://media/<message_id>).

    Scoped to ctx.deps.chat_id: the agent can only pull files from messages
    it can see. Oversize media is refused before any download happens.
    """
    if not rest.startswith("/media/"):
        raise ValueError(
            f"Invalid chat:// media target {rest!r}; use chat://media/<message_id>"
        )
    msg_id_str = rest.removeprefix("/media/")
    if not msg_id_str.isdigit():
        raise ValueError(
            f"Invalid chat:// media target {rest!r}; expected a message id."
        )
    client = ctx.deps.client
    message = await client.get_messages(ctx.deps.chat_id, int(msg_id_str))
    if message is None or not message.media:
        raise _NoMediaError(f"Message {msg_id_str} has no downloadable media.")
    return await _download_tg_bytes(client, message, f"message {msg_id_str}")


def _tme_message_parts(url: str) -> tuple[str, str] | None:
    """(chat_ref, msg_id) for a public t.me message link, else None.

    Accepts https://t.me/<username>/<id> on t.me or telegram.me hosts.
    Private-channel share links (t.me/c/...) are deliberately not accepted:
    they would let the agent read media from private chats beyond the
    current conversation. Public channels are readable by anyone.
    """
    parsed = urlsplit(url)
    if parsed.hostname not in ("t.me", "telegram.me"):
        return None
    parts = parsed.path.strip("/").split("/")
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0], parts[1]
    return None


async def _download_tme_media(ctx: RunContext[datatype.ContextDeps], url: str) -> bytes:
    """Download the media of a public t.me message link.

    Public channels are readable by any bot; groups the bot is not a member
    of, private channels and invite links fail with a clear error.
    Size-limited like chat://media.
    """
    parts = _tme_message_parts(url)
    if parts is None:
        raise ValueError(f"Not a t.me message link: {url}")
    chat_ref, msg_id_str = parts
    client = ctx.deps.client
    try:
        chat = await client.get_chat(chat_ref)
    except Exception:
        raise ValueError(
            f"Cannot resolve {chat_ref!r} from {url}; the chat may be "
            f"private or the bot may not be a member."
        ) from None
    message = await client.get_messages(chat.id, int(msg_id_str))
    if message is None or not message.media:
        raise _NoMediaError(
            f"Message {msg_id_str} in {chat_ref} has no downloadable media."
        )
    return await _download_tg_bytes(
        client, message, f"message {msg_id_str} in {chat_ref}"
    )


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
    if protocol in ("work://", "sandbox://"):
        if raw:
            raw_bytes = await read_bytes(path, ctx)
            return raw_bytes.decode("utf-8", errors="replace")
        if protocol == "work://":
            content = await workspace.read_file(
                _session_key(ctx), rest, start_line, max_lines
            )
        else:
            content = await _read_sandbox_lines(ctx, rest, start_line, max_lines)
        if content is None:
            raise ValueError(f"File not found: {path}")
        return content
    if protocol == "persist://":
        data = await _download_persisted(ctx, rest)
        if raw:
            return data.decode("utf-8", errors="replace")
        text = data.decode("utf-8", errors="replace")
        lines = text.splitlines()
        selected = lines[start_line - 1 : start_line - 1 + max_lines]
        return "\n".join(selected)
    if protocol == "chat://":
        if rest.startswith("/media/"):
            data = await _download_chat_media(ctx, rest)
        else:
            return await _read_chat(ctx, rest, max_lines)
        if raw:
            return data.decode("utf-8", errors="replace")
        text = data.decode("utf-8", errors="replace")
        lines = text.splitlines()
        selected = lines[start_line - 1 : start_line - 1 + max_lines]
        return "\n".join(selected)
    if protocol == "http":
        if _tme_message_parts(rest) is not None:
            try:
                data = await _download_tme_media(ctx, rest)
            except _NoMediaError:
                # A plain-text t.me post has no media to download; fall back
                # to the web text extraction, which renders the post text.
                result = await web.fetch_web_page(ctx, rest)
                if not result.success:
                    raise ValueError(result.error or "fetch failed")
                return result.content or ""
            if raw:
                return data.decode("utf-8", errors="replace")
            text = data.decode("utf-8", errors="replace")
            lines = text.splitlines()
            selected = lines[start_line - 1 : start_line - 1 + max_lines]
            return "\n".join(selected)
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
    - persist://report.txt    — a file the agent persisted for this chat
    - chat://media/123        — the media of message 123 in this chat
    - https://t.me/MoreACG/27411 — the media of a public t.me message
    - chat://info             — information about the current group
    - chat://history?direction=latest|before|after|between&count=N&anchor_id=N&start_id=N&end_id=N
                              — messages from the current group
    - https://example.com     — a web page as markdown/text

    Use start_line/max_lines to page through kmua://, work:// and
    persist:// targets (1-indexed; max_lines up to 1500).
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
    content: str | bytes | None = None,
) -> str:
    """Write content to a target. The path is the destination; content is the payload.

    Protocols:
    - work://notes/hello.html — save content as a file in the chat's workspace
    - persist://report.txt    — persist a file for this chat: it is sent as a
        document to the chat and recorded; later runs can read, list, delete
        and overwrite it by name. The chat message stays after delete.
    - memory://               — store content as a fact about this group in its
        long-term memory

    content can be plain text or a reference to another target whose content
    is used as the payload — e.g. work://notes/hello.html (workspace file) or
    kmua://kmua/services/wechat.py (codebase file, read-only), handy for
    copying files between targets. A chat://media/<message_id> reference
    downloads a message's media from this chat, and an https://t.me/... link
    from a public Telegram chat (both size-limited). Binary payloads must go
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
    to make old_text unique; when it matches nothing or several places the
    edit reports an error. Pass replace_all=True to change every occurrence.
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
    - work://subdir       — workspace subdirectory
    - persist://          — files persisted for this chat
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
    """Delete a file from the workspace or the persisted set.

    work:// removes the local file. persist:// removes the record only -
    the document message stays in chat history.
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
