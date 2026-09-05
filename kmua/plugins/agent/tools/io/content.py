"""The read-side content dispatcher: resolve any protocol target to text."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

from pydantic_ai import RunContext

from kmua.config import app_config

from .. import bot, code_repo, datatype, db, web, workspace
from .media import _download_chat_media, _download_tme_media, _tme_message_parts
from .protocols import _require, _split_target
from .targets import _download_persisted, _read_sandbox_lines, read_bytes


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
        known = {"before", "after", "from_id", "to_id", "count"}
        if any(key not in known for key in query):
            return (
                "Error: unknown query parameters; supported: before=<id>, "
                "after=<id>, from_id=<a>&to_id=<b>, count=N."
            )
        try:
            params = {
                key: int(values[0])
                for key in ("before", "after", "from_id", "to_id", "count")
                if (values := query.get(key))
            }
        except (ValueError, IndexError):
            return (
                "Error: invalid query parameters; expected integers for "
                "before/after/from_id/to_id/count."
            )
        return await bot.get_history_messages(ctx, **params)
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
            if raw:
                data = await _download_tme_media(ctx, rest)
                return data.decode("utf-8", errors="replace")
            # Public t.me message link: prefer the message itself over the
            # t.me web page — the page is an HTML shell, the message carries
            # the real text/caption.
            tg_result = await web._fetch_telegram_message(ctx, rest)
            if tg_result is not None and tg_result.success and tg_result.content:
                text = tg_result.content
            else:
                # Unresolvable chat or deleted message: fall back to the
                # public web page extraction.
                if app_config.agent_crawl_api_url:
                    web_result = await web._fetch_crawl_api(rest)
                else:
                    web_result = await web._fetch_http(rest)
                if not web_result.success:
                    raise ValueError(
                        web_result.error
                        or (tg_result.error if tg_result else None)
                        or "fetch failed"
                    )
                text = web_result.content or ""
            lines = text.splitlines()
            selected = lines[start_line - 1 : start_line - 1 + max_lines]
            return "\n".join(selected)
        result = await web.fetch_web_page(ctx, rest)
        if not result.success:
            raise ValueError(result.error or "fetch failed")
        return result.content or ""
    raise ValueError(f"Target {path} is not readable.")
