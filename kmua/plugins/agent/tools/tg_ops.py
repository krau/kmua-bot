"""A single tool that calls Telegram methods on the current chat.

The API mirrors the Telegram Bot API: `method` is a Bot API method name and
`params` uses the Bot API field names. Only a whitelist of sending/expressive
methods is exposed, plus kmua-specific extensions. chat_id is always the
current chat and cannot be overridden.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

import pyrogram
from pydantic_ai import RunContext

from kmua.common.safe_http import DEFAULT_MAX_BYTES, UnsafeUrlError, safe_download_bytes
from kmua.logger import logger

from .. import datatype
from . import block, code_repo, io, send_ops, workspace

# method -> (pyrogram client method, allowed params, required params)
_METHODS: dict[str, tuple[str, set[str], set[str]]] = {
    "sendMessage": (
        "send_message",
        {"text", "parse_mode", "disable_web_page_preview", "reply_to_message_id"},
        {"text"},
    ),
    "sendPhoto": (
        "send_photo",
        {"photo", "caption", "has_spoiler", "reply_to_message_id"},
        {"photo"},
    ),
    "sendDocument": (
        "send_document",
        {"document", "content", "file_name", "caption", "reply_to_message_id"},
        set(),
    ),
    "sendReaction": (
        "send_reaction",
        {"message_id", "emoji"},
        {"message_id", "emoji"},
    ),
    "sendPoll": (
        "send_poll",
        {
            "question",
            "options",
            "is_anonymous",
            "allows_multiple_answers",
            "reply_to_message_id",
        },
        {"question", "options"},
    ),
    "sendDice": ("send_dice", {"emoji"}, set()),
    "sendAudio": (
        "send_audio",
        {"audio", "caption", "reply_to_message_id"},
        {"audio"},
    ),
    "sendVideo": (
        "send_video",
        {"video", "caption", "reply_to_message_id"},
        {"video"},
    ),
    "sendVoice": (
        "send_voice",
        {"voice", "caption", "reply_to_message_id"},
        {"voice"},
    ),
    "sendAnimation": (
        "send_animation",
        {"animation", "caption", "reply_to_message_id"},
        {"animation"},
    ),
}

_MEDIA_FIELDS = {
    "photo",
    "document",
    "audio",
    "video",
    "voice",
    "animation",
}


def _session_key(ctx: RunContext[datatype.ContextDeps]) -> str:
    """Workspace session key: chat id for groups, user id for private chats."""
    deps = ctx.deps
    return str(deps.chat_id) if deps.chat_id != deps.user_id else str(deps.user_id)


_KMUA_EXTENSIONS = {
    "scheduleMessage",
    "blockUser",
}


def _method_list() -> str:
    standard = ", ".join(sorted(_METHODS))
    ext = ", ".join(sorted(_KMUA_EXTENSIONS))
    return f"{standard}, {ext}"


async def _call_kmua_extension(
    ctx: RunContext[datatype.ContextDeps], method: str, params: dict[str, Any]
) -> str:
    if method == "scheduleMessage":
        text = params.get("text")
        schedule_time = params.get("schedule_time")
        if not text or not schedule_time:
            return "Error: scheduleMessage requires text and schedule_time."
        return await send_ops.schedule_message(ctx, str(schedule_time), text=str(text))
    if method == "blockUser":
        try:
            duration = int(params.get("duration_minutes") or 0)
        except (TypeError, ValueError):
            return "Error: blockUser requires duration_minutes (integer)."
        if duration <= 0:
            return "Error: blockUser requires duration_minutes (1-10080)."
        user_id = params.get("user_id")
        return await block.block_user(
            ctx,
            duration,
            int(user_id) if user_id is not None else None,
            str(params.get("reason") or ""),
        )
    return f"Error: Unknown method: {method}"


async def _convert_params(
    ctx: RunContext[datatype.ContextDeps],
    method: str,
    params: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """Map Bot API params to pyrogram kwargs. Returns (kwargs, error)."""
    _, allowed, required = _METHODS[method]
    unknown = set(params) - allowed - {"chat_id"}
    if unknown:
        return None, (
            f"Error: Unknown field(s) for {method}: {', '.join(sorted(unknown))}. "
            f"Allowed: {', '.join(sorted(allowed))}."
        )
    if "chat_id" in params:
        return None, "Error: chat_id is always the current chat; do not pass it."
    if method == "sendDocument" and "content" in params and "document" in params:
        return None, "Error: sendDocument takes either document or content, not both."
    if (
        method == "sendDocument"
        and "content" not in params
        and "document" not in params
    ):
        return None, "Error: sendDocument requires document or content."
    missing = required - set(params)
    if missing:
        return (
            None,
            f"Error: Missing required field(s) for {method}: {', '.join(sorted(missing))}.",
        )
    kwargs: dict[str, Any] = {}
    for key, value in params.items():
        if key == "reply_to_message_id":
            kwargs["reply_parameters"] = pyrogram.types.ReplyParameters(
                message_id=int(value)
            )
        elif key == "disable_web_page_preview":
            kwargs["link_preview_options"] = pyrogram.types.LinkPreviewOptions(
                is_disabled=bool(value)
            )
        elif key == "options":
            kwargs["options"] = list(value)
        elif method == "sendDocument" and key == "content":
            kwargs["document"] = _named_media(
                method,
                str(params.get("file_name") or "document.txt"),
                str(value).encode("utf-8"),
            )
        elif (
            key in _MEDIA_FIELDS
            and isinstance(value, str)
            and value.startswith("kmua://")
        ):
            # kmua:// references read a file from the bot's own codebase
            # (read-only, same access as the read tool).
            rest = "/" + value[len("kmua://") :].lstrip("/")
            try:
                agent = await code_repo.get_code_agentfs()
                if agent is None:
                    return None, "Error: Code repository not initialized."
                raw = await agent.fs.read_file(rest)
                if isinstance(raw, str):
                    raw = raw.encode("utf-8")
            except Exception as e:
                return None, f"Error: {e}"
            kwargs[key] = _named_media(method, value, raw)
        elif (
            key in _MEDIA_FIELDS
            and isinstance(value, str)
            and value.startswith("work://")
        ):
            # work:// references read a file from this session's workspace.
            rest = "/" + value[len("work://") :].lstrip("/")
            try:
                raw = await workspace.read_file_bytes(_session_key(ctx), rest)
            except Exception as e:
                return None, f"Error: {e}"
            kwargs[key] = _named_media(method, value, raw)
        elif (
            key in _MEDIA_FIELDS
            and isinstance(value, str)
            and value.startswith("sandbox://")
        ):
            # sandbox:// references read a file from this session's shell
            # sandbox (same symlink-guarded access as the io tools).
            try:
                raw = await io.read_bytes(value, ctx)
            except Exception as e:
                return None, f"Error: {e}"
            kwargs[key] = _named_media(method, value, raw)
        elif (
            key in _MEDIA_FIELDS
            and isinstance(value, str)
            and value.startswith(("http://", "https://"))
        ):
            # Media URLs are downloaded through the SSRF-guarded client so
            # pyrogram never fetches an arbitrary address itself. The in-memory
            # file must carry a .name so pyrogram can infer type and file name
            # (its docs require file-like objects to set ".name").
            try:
                raw = await safe_download_bytes(value, max_bytes=DEFAULT_MAX_BYTES)
            except UnsafeUrlError as e:
                return None, f"Error: {e}"
            except Exception as e:
                return (
                    None,
                    f"Error: Failed to download {key}: {e.__class__.__name__}",
                )
            kwargs[key] = _named_media(method, value, raw)
        elif key in _MEDIA_FIELDS:
            return None, (
                f"Error: {key} must be an http(s) URL, a work:// file reference "
                "or a kmua:// codebase file."
            )
        else:
            kwargs[key] = value
    return kwargs, None


# Fallback extensions per method when the URL carries no recognizable one.
_DEFAULT_MEDIA_EXT: dict[str, str] = {
    "sendPhoto": ".jpg",
    "sendDocument": ".bin",
    "sendAudio": ".mp3",
    "sendVideo": ".mp4",
    "sendVoice": ".ogg",
    "sendAnimation": ".gif",
}


def _named_media(method: str, url: str, raw: bytes) -> BytesIO:
    """Wrap bytes in a BytesIO carrying a filename for pyrogram.

    url is an http(s) URL, a work:// reference or a plain file name.
    """
    from urllib.parse import unquote, urlparse

    if url.startswith("work://"):
        path_part = url[len("work://") :].lstrip("/")
    elif url.startswith(("http://", "https://")):
        path_part = unquote(urlparse(url).path)
    else:
        path_part = url
    name = path_part.rsplit("/", 1)[-1]
    if not name or name in (".", ".."):
        name = "file"
    suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if not suffix:
        # No extension: fall back to the method's default so pyrogram can
        # infer the media type. Any explicit extension is kept as-is.
        name += _DEFAULT_MEDIA_EXT.get(method, ".bin")
    media = BytesIO(raw)
    media.name = name
    return media


async def tg(
    ctx: RunContext[datatype.ContextDeps],
    method: str,
    params: dict[str, Any] = {},
) -> str:
    """Call a Telegram method on the current chat, using Telegram Bot API naming.

    chat_id is always the current chat — do not pass it. Unknown methods,
    unknown fields and missing required fields are rejected with an error.

    Standard methods (params follow Bot API field names):
    - sendMessage: text, parse_mode (HTML / MarkdownV2), disable_web_page_preview, reply_to_message_id
    - sendPhoto: photo (http(s) URL, work:// or kmua:// reference), caption, has_spoiler, reply_to_message_id
    - sendDocument: document (http(s) URL or a work:// / kmua:// reference)
      OR content (plain text made into the document), plus file_name, caption,
      reply_to_message_id
    - sendReaction: message_id, emoji
    - sendPoll: question, options (2-8 strings), is_anonymous, allows_multiple_answers, reply_to_message_id
    - sendDice: emoji (🎲 🎯 🎳 🎰 🎲 variants)
    - sendAudio / sendVideo / sendVoice / sendAnimation: the media field, caption, reply_to_message_id

    Media fields accept a public http(s) URL, a work:// file reference from
    this chat's workspace, or a kmua:// codebase file.

    kmua extensions:
    - scheduleMessage: text, schedule_time (ISO 8601, must be in the future).
    - blockUser: duration_minutes (1-10080), user_id (optional, defaults to the
      person who asked), reason (optional).

    Example: tg("sendPoll", {"question": "Lunch?", "options": ["noodles", "rice"]})
    """
    if ctx.deps.message is None or ctx.deps.message.id is None:
        return "Error: Current message context is unavailable."
    if ctx.deps.is_guest_mode:
        return "Error: This tool is not available in guest mode."
    if not isinstance(params, dict):
        return "Error: params must be an object with Bot API field names."

    if method in _KMUA_EXTENSIONS:
        return await _call_kmua_extension(ctx, method, params)
    if method not in _METHODS:
        return f"Error: Unknown method: {method}. Supported: {_method_list()}."

    kwargs, error = await _convert_params(ctx, method, params)
    if error:
        return error
    assert kwargs is not None
    client_method = _METHODS[method][0]
    try:
        result = await getattr(ctx.deps.client, client_method)(
            chat_id=ctx.deps.chat_id, **kwargs
        )
    except Exception as e:
        logger.error(f"tg {method} error: {e.__class__.__name__}: {e}")
        return f"Error: {method} failed: {e.__class__.__name__}"
    message_id = getattr(result, "message_id", None)
    if message_id is not None:
        return f"{method} sent (message_id={message_id})."
    return f"{method} OK."


__all__ = ["tg"]
