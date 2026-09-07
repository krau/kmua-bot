"""Telegram and file-media reads with native Pydantic AI returns."""

from __future__ import annotations

import asyncio
import builtins
import mimetypes
from dataclasses import dataclass
from io import BytesIO
from typing import Any
from urllib.parse import urlsplit

from pydantic_ai import BinaryContent, RunContext, ToolReturn

from kmua.config import app_config
from kmua.logger import logger

from ... import provider
from .. import datatype
from .protocols import _split_target


@dataclass(frozen=True, slots=True)
class MediaPayload:
    """A non-text payload that must not be decoded into a tool string."""

    data: bytes
    media_type: str
    label: str


class _NoMediaError(ValueError):
    """The message has no downloadable media (lets read fall back to text)."""


_TEXT_MEDIA_TYPES = {
    "application/javascript",
    "application/json",
    "application/ld+json",
    "application/toml",
    "application/xml",
    "application/xhtml+xml",
    "application/x-www-form-urlencoded",
    "application/yaml",
}


def _normalize_media_type(media_type: str | None) -> str | None:
    if not media_type:
        return None
    return media_type.split(";", 1)[0].strip().lower() or None


def _is_text_media_type(media_type: str | None) -> bool:
    normalized = _normalize_media_type(media_type)
    return bool(
        normalized
        and (
            normalized.startswith("text/")
            or normalized in _TEXT_MEDIA_TYPES
            or normalized.endswith("+json")
            or normalized.endswith("+xml")
        )
    )


def _looks_like_text(data: bytes) -> bool:
    if not data:
        return True
    if b"\x00" in data:
        return False
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    controls = sum(1 for char in text if ord(char) < 32 and char not in "\n\r\t\f")
    return controls <= max(1, len(text) // 100)


def _sniff_media_type(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and len(data) >= 12:
        form = data[8:12]
        if form == b"WEBP":
            return "image/webp"
        if form == b"WAVE":
            return "audio/wav"
        if form == b"AVI ":
            return "video/x-msvideo"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"PK\x03\x04"):
        return "application/zip"
    if data.startswith(b"OggS"):
        return "audio/ogg"
    if data.startswith(b"ID3") or (
        len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0
    ):
        return "audio/mpeg"
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "video/mp4"
    return None


def _path_media_type(path: str) -> str | None:
    parsed = urlsplit(path)
    filename = parsed.path or path
    guessed, _ = mimetypes.guess_type(filename)
    return _normalize_media_type(guessed)


def _media_payload_from_bytes(
    path: str,
    data: bytes,
    *,
    label: str | None = None,
    declared_media_type: str | None = None,
) -> MediaPayload | None:
    """Classify bytes without ever converting a binary payload to replacement text."""
    declared = _normalize_media_type(declared_media_type)
    guessed = _path_media_type(path)
    sniffed = _sniff_media_type(data)
    candidate = sniffed or declared or guessed

    if (declared and _is_text_media_type(declared)) or (
        not declared and guessed and _is_text_media_type(guessed)
    ):
        if _looks_like_text(data):
            return None
    elif not declared and not guessed and not sniffed and _looks_like_text(data):
        return None

    return MediaPayload(
        data=data,
        media_type=candidate or "application/octet-stream",
        label=label or path,
    )


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
    """Download one message's media with the configured timeout and cap."""
    if getattr(message, "paid_media", None):
        raise ValueError(f"{what}: paid media is not supported.")
    size = _tg_media_size(message)
    if size is None:
        # A truthy message.media is not enough: web-page previews count as
        # media but carry no downloadable file.
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


async def _get_chat_media_message(
    ctx: RunContext[datatype.ContextDeps], rest: str
) -> Any:
    """Resolve chat://media/<message_id> within the current chat."""
    if not rest.startswith("/media/"):
        raise ValueError(
            f"Invalid chat:// media target {rest!r}; use chat://media/<message_id>"
        )
    msg_id_str = rest.removeprefix("/media/")
    if not msg_id_str.isdigit():
        raise ValueError(
            f"Invalid chat:// media target {rest!r}; expected a message id."
        )
    message = await ctx.deps.client.get_messages(ctx.deps.chat_id, int(msg_id_str))
    if message is None or not message.media:
        raise _NoMediaError(f"Message {msg_id_str} has no downloadable media.")
    return message


async def _download_chat_media(
    ctx: RunContext[datatype.ContextDeps], rest: str
) -> bytes:
    """Download the media of chat://media/<message_id>."""
    message = await _get_chat_media_message(ctx, rest)
    return await _download_tg_bytes(
        ctx.deps.client, message, f"message {rest.removeprefix('/media/')}"
    )


def _tme_message_parts(url: str) -> tuple[str, str] | None:
    """Return (chat_ref, msg_id) for a public t.me message link."""
    parsed = urlsplit(url)
    if parsed.hostname not in ("t.me", "telegram.me"):
        return None
    parts = parsed.path.strip("/").split("/")
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0], parts[1]
    return None


async def _get_tme_message(ctx: RunContext[datatype.ContextDeps], url: str) -> Any:
    """Resolve a public t.me message link to its Telegram message."""
    parts = _tme_message_parts(url)
    if parts is None:
        raise ValueError(f"Not a t.me message link: {url}")
    chat_ref, msg_id_str = parts
    try:
        chat = await ctx.deps.client.get_chat(chat_ref)
    except Exception:
        raise ValueError(
            f"Cannot resolve {chat_ref!r} from {url}; the chat may be private or "
            f"the bot may not be a member."
        ) from None
    message = await ctx.deps.client.get_messages(chat.id, int(msg_id_str))
    if message is None or not message.media:
        raise _NoMediaError(
            f"Message {msg_id_str} in {chat_ref} has no downloadable media."
        )
    return message


async def _download_tme_media(ctx: RunContext[datatype.ContextDeps], url: str) -> bytes:
    """Download media from a public t.me message link."""
    message = await _get_tme_message(ctx, url)
    chat_ref, msg_id_str = _tme_message_parts(url) or ("chat", "?")
    return await _download_tg_bytes(
        ctx.deps.client, message, f"message {msg_id_str} in {chat_ref}"
    )


def _tg_media_type(message: Any) -> str | None:
    """Return the MIME type for a Telegram message's downloadable payload."""
    if getattr(message, "paid_media", None):
        return "application/octet-stream"
    if getattr(message, "photo", None):
        return "image/jpeg"
    if getattr(message, "sticker", None):
        sticker = message.sticker
        if getattr(sticker, "is_video", False):
            return "video/webm"
        if getattr(sticker, "is_animated", False):
            return "application/x-tgsticker"
        return "image/webp"
    defaults = {
        "video": "video/mp4",
        "audio": "audio/mpeg",
        "voice": "audio/ogg",
        "animation": "video/mp4",
        "video_note": "video/mp4",
    }
    for attr, default in defaults.items():
        payload = getattr(message, attr, None)
        if payload is not None:
            return _normalize_media_type(getattr(payload, "mime_type", None)) or default
    document = getattr(message, "document", None)
    if document is not None:
        mime = _normalize_media_type(getattr(document, "mime_type", None))
        if mime:
            return mime
        guessed, _ = mimetypes.guess_type(getattr(document, "file_name", None) or "")
        return _normalize_media_type(guessed)
    return None


def _run_model_matches_multimodal(ctx: RunContext[datatype.ContextDeps]) -> bool:
    if not app_config.agent_multimodal:
        return False
    spec = app_config.agent_model_multimodal or app_config.agent_model
    model_name = getattr(ctx.model, "model_name", None)
    if not spec or not model_name:
        return False
    return model_name == provider._parse_spec(spec)[1]


def _run_model_accepts_images(ctx: RunContext[datatype.ContextDeps]) -> bool:
    """Whether the current run's model can receive configured image parts."""
    return (
        "photo" in app_config.agent_multimodal_inputs
        and _run_model_matches_multimodal(ctx)
    )


def _run_model_accepts_media(
    ctx: RunContext[datatype.ContextDeps], media_type: str
) -> bool:
    """Whether the current run can receive this MIME type as native content."""
    if media_type.startswith("image/"):
        return _run_model_accepts_images(ctx)
    if not _run_model_matches_multimodal(ctx):
        return False
    if media_type.startswith("video/"):
        return "video" in app_config.agent_multimodal_inputs
    if media_type.startswith("audio/"):
        return "audio" in app_config.agent_multimodal_inputs
    return media_type in app_config.agent_multimodal_inputs


def _read_transcription_model(
    ctx: RunContext[datatype.ContextDeps],
) -> Any | None:
    if not app_config.agent_multimodal:
        return None
    selected = getattr(ctx.deps, "multimodal_model", None)
    if selected is not None:
        return selected
    spec = app_config.agent_model_multimodal or app_config.agent_model
    if not spec:
        return None
    try:
        return provider.make_chat_model(spec)
    except Exception as e:
        logger.error(
            f"read transcription model unavailable: {e.__class__.__name__} - {e}"
        )
        return None


def _binary_read_guidance(label: str, media_type: str, reason: str) -> str:
    return (
        f"{label} contains binary content ({media_type}). {reason} "
        "The bytes were not decoded as text."
    )


async def _transcribe_media_tool_return(
    ctx: RunContext[datatype.ContextDeps],
    *,
    label: str,
    media_type: str,
    data: bytes | None,
) -> str:
    """Turn a read-side binary payload into text for transcribe-mode runs."""
    if data is None:
        return _binary_read_guidance(
            label, media_type, "The media bytes were unavailable for transcription."
        )
    model = _read_transcription_model(ctx)
    if model is None:
        return _binary_read_guidance(
            label,
            media_type,
            "No multimodal transcription model is available.",
        )
    from ...prompt import transcribe_binary_content

    try:
        description = await transcribe_binary_content(model, data, media_type)
    except Exception as e:
        logger.error(f"read media transcription failed: {e.__class__.__name__} - {e}")
        description = None
    if not description:
        return _binary_read_guidance(label, media_type, "Media transcription failed.")
    return f"[Media transcription from {label} ({media_type})]:\n{description}"


def _media_tool_return(
    ctx: RunContext[datatype.ContextDeps],
    *,
    label: str,
    media_type: str,
    data: bytes | None,
) -> ToolReturn:
    """Return media natively, or explain why the current model cannot view it."""
    if not _run_model_accepts_media(ctx, media_type):
        return ToolReturn(
            return_value=(
                f"{label} contains binary content ({media_type}). The current model "
                f"cannot inspect this media."
            )
        )
    if data is None:
        return ToolReturn(
            return_value=f"{label} is {media_type}, but its bytes could not be read."
        )
    kind = "Image" if media_type.startswith("image/") else "Media"
    text = f"[{kind} from {label} ({media_type})]"
    return ToolReturn(
        return_value=text,
        content=[text, BinaryContent(data=data, media_type=media_type)],
    )


def _page_text(data: bytes, start_line: int, max_lines: int) -> str:
    lines = data.decode("utf-8", errors="replace").splitlines()
    start_idx = start_line - 1
    return "\n".join(lines[start_idx : start_idx + max_lines])


async def _native_media_return(
    ctx: RunContext[datatype.ContextDeps],
    path: str,
    what: str,
    *,
    image_only: bool = False,
    start_line: int = 1,
    max_lines: int = 1500,
) -> str | ToolReturn | None:
    """Return a Telegram media target as native content or safe text."""
    protocol, rest = _split_target(path)
    try:
        if protocol == "chat://":
            message = await _get_chat_media_message(ctx, rest)
            label = f"message {rest.removeprefix('/media/')}"
        elif protocol == "http":
            message = await _get_tme_message(ctx, path)
            label = what
        else:
            return None
    except Exception:
        # Resolution failures belong to the normal text/web fallback path.
        return None

    media_type = _tg_media_type(message)
    data: bytes | None = None
    if media_type is None:
        if image_only:
            return None
        if _tg_media_size(message) is None:
            return None
        data = await _download_tg_bytes(ctx.deps.client, message, what)
        payload = _media_payload_from_bytes(path, data, label=label)
        if payload is None:
            return _page_text(data, start_line, max_lines)
        media_type = payload.media_type
        data = payload.data
    if _is_text_media_type(media_type):
        return None
    if image_only and not media_type.startswith("image/"):
        return None
    caption = (getattr(message, "caption", None) or "").strip()
    if app_config.agent_multimodal_mode == "transcribe":
        if data is None:
            data = await _download_tg_bytes(ctx.deps.client, message, what)
        result = await _transcribe_media_tool_return(
            ctx,
            label=label,
            media_type=media_type,
            data=data,
        )
        if caption:
            result += f"\n[Caption]: {caption}"
        return result
    if not _run_model_accepts_media(ctx, media_type):
        return _media_tool_return(ctx, label=label, media_type=media_type, data=None)
    if data is None:
        data = await _download_tg_bytes(ctx.deps.client, message, what)
    result = _media_tool_return(ctx, label=label, media_type=media_type, data=data)
    if caption and result.content:
        result.return_value = f"{result.return_value}\n[Caption]: {caption}"
        result.content = [
            f"{result.content[0]}\n[Caption]: {caption}",
            *result.content[1:],
        ]
    return result


async def _native_image_return(
    ctx: RunContext[datatype.ContextDeps],
    path: str,
    what: str,
    *,
    start_line: int = 1,
    max_lines: int = 1500,
) -> str | ToolReturn | None:
    """Compatibility wrapper for callers that only request still images."""
    if not _run_model_accepts_images(ctx):
        return None
    return await _native_media_return(
        ctx,
        path,
        what,
        image_only=True,
        start_line=start_line,
        max_lines=max_lines,
    )
