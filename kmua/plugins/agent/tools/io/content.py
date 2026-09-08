"""The read-side dispatcher for text and native binary content."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

from pydantic_ai import RunContext

from kmua.config import app_config

from .. import bot, datatype, db, web
from .media import (
    MediaPayload,
    _download_chat_media,
    _download_tme_media,
    _media_payload_from_bytes,
    _tme_message_parts,
)
from .protocols import _require, _split_target
from .targets import _download_persisted, read_bytes


def _format_chat_info(info: db.ChatInfo) -> str:
    data = info.model_dump(exclude_none=True)
    return json.dumps(data, ensure_ascii=False, indent=2)


def _decode_text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _page_lines(text: str, start_line: int, max_lines: int) -> str | None:
    lines = text.splitlines()
    start_idx = start_line - 1
    if start_idx >= len(lines):
        return None
    return "\n".join(lines[start_idx : start_idx + max_lines])


def _numbered_file(path: str, text: str, start_line: int, max_lines: int) -> str | None:
    lines = text.splitlines()
    start_idx = start_line - 1
    if start_idx >= len(lines):
        return None
    end_idx = min(start_idx + max_lines, len(lines))
    result: list[str] = []
    if start_idx > 0:
        result.append(f"... ({start_idx} lines above)")
    for i, line in enumerate(lines[start_idx:end_idx], start=start_line):
        result.append(f"{i:4d}: {line}")
    if end_idx < len(lines):
        result.append(f"... ({len(lines) - end_idx} lines below)")
    header = f"File: {path} (lines {start_line}-{end_idx} of {len(lines)})"
    return f"{header}\n{'=' * len(header)}\n" + "\n".join(result)


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
        known = {"before", "after", "from_id", "to_id", "count", "reply_chain_of"}
        if any(key not in known for key in query):
            return (
                "Error: unknown query parameters; supported: before=<id>, "
                "after=<id>, from_id=<a>&to_id=<b>, "
                "reply_chain_of=<id>, count=N."
            )
        try:
            params = {
                key: int(values[0])
                for key in (
                    "before",
                    "after",
                    "from_id",
                    "to_id",
                    "count",
                    "reply_chain_of",
                )
                if (values := query.get(key))
            }
        except (ValueError, IndexError):
            return (
                "Error: invalid query parameters; expected integers for "
                "before/after/from_id/to_id/count/reply_chain_of."
            )
        return await bot.get_history_messages(ctx, **params)
    return f"Error: Unknown chat:// target {parts.path}; use /info or /history."


async def _read_target_bytes(path: str, ctx: RunContext[datatype.ContextDeps]) -> bytes:
    try:
        return await read_bytes(path, ctx)
    except Exception as e:
        if isinstance(e, FileNotFoundError) or "ENOENT" in str(e):
            raise ValueError(f"File not found: {path}") from e
        raise


async def _read_content(
    ctx: RunContext[datatype.ContextDeps],
    path: str,
    start_line: int = 1,
    max_lines: int = 1500,
    raw: bool = False,
) -> str | MediaPayload:
    """Resolve a target without converting non-text bytes to replacement text."""
    protocol, rest = _split_target(path)
    denied = _require(protocol, ctx.deps)
    if denied:
        raise ValueError(denied)

    if protocol == "kmua://":
        data = await _read_target_bytes(path, ctx)
        payload = _media_payload_from_bytes(path, data, label=path)
        if payload is not None:
            return payload
        text = _decode_text(data)
        if raw:
            return text
        content = _numbered_file(rest, text, start_line, max_lines)
        if content is None:
            raise ValueError(f"File not found: {path}")
        return content

    if protocol in ("work://", "sandbox://"):
        data = await _read_target_bytes(path, ctx)
        payload = _media_payload_from_bytes(path, data, label=path)
        if payload is not None:
            return payload
        text = _decode_text(data)
        if raw:
            return text
        if protocol == "work://":
            content = _numbered_file(rest, text, start_line, max_lines)
        else:
            content = _page_lines(text, start_line, max_lines)
        if content is None:
            raise ValueError(f"File not found: {path}")
        return content

    if protocol == "persist://":
        data = await _download_persisted(ctx, rest)
        payload = _media_payload_from_bytes(path, data, label=path)
        if payload is not None:
            return payload
        text = _decode_text(data)
        if raw:
            return text
        content = _page_lines(text, start_line, max_lines)
        return content or ""

    if protocol == "chat://":
        if rest.startswith("/media/"):
            data = await _download_chat_media(ctx, rest)
            payload = _media_payload_from_bytes(
                path,
                data,
                label=f"message {rest.removeprefix('/media/')}",
            )
            if payload is not None:
                return payload
            text = _decode_text(data)
            if raw:
                return text
            return _page_lines(text, start_line, max_lines) or ""
        return await _read_chat(ctx, rest, max_lines)

    if protocol == "http":
        if _tme_message_parts(rest) is not None:
            if raw:
                data = await _download_tme_media(ctx, rest)
                payload = _media_payload_from_bytes(path, data, label=path)
                if payload is not None:
                    return payload
                return _decode_text(data)
            # Prefer the Telegram message over the public HTML shell. When
            # resolution fails, the normal web fetch remains the fallback.
            tg_result = await web._fetch_telegram_message(ctx, rest)
            if tg_result is not None and tg_result.success and tg_result.content:
                text = tg_result.content
            else:
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
                binary = getattr(web_result, "binary", None)
                if binary is not None:
                    return MediaPayload(
                        data=binary,
                        media_type=getattr(web_result, "media_type", None)
                        or "application/octet-stream",
                        label=path,
                    )
                text = web_result.content or ""
            return _page_lines(text, start_line, max_lines) or ""

        result = await web.fetch_web_page(ctx, rest)
        if not result.success:
            raise ValueError(result.error or "fetch failed")
        binary = getattr(result, "binary", None)
        if binary is not None:
            return MediaPayload(
                data=binary,
                media_type=getattr(result, "media_type", None)
                or "application/octet-stream",
                label=path,
            )
        return result.content or ""

    raise ValueError(f"Target {path} is not readable.")
