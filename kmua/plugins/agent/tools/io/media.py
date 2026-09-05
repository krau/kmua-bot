"""Telegram media download: chat://media, public t.me links, native image
returns for multimodal models."""

from __future__ import annotations

import asyncio
import builtins
from io import BytesIO
from typing import Any
from urllib.parse import urlsplit

from pydantic_ai import BinaryContent, RunContext, ToolReturn

from kmua.config import app_config

from ... import provider
from .. import datatype
from .protocols import _split_target


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


async def _get_chat_media_message(
    ctx: RunContext[datatype.ContextDeps], rest: str
) -> Any:
    """Resolve chat://media/<message_id> to the message carrying the media.

    Scoped to ctx.deps.chat_id: the agent can only pull files from messages
    it can see. Raises _NoMediaError when there is nothing downloadable.
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
    return message


async def _download_chat_media(
    ctx: RunContext[datatype.ContextDeps], rest: str
) -> bytes:
    """Download the media of a message in the current chat
    (chat://media/<message_id>). Oversize media is refused before any
    download happens.
    """
    message = await _get_chat_media_message(ctx, rest)
    return await _download_tg_bytes(
        ctx.deps.client, message, f"message {rest.removeprefix('/media/')}"
    )


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


async def _get_tme_message(ctx: RunContext[datatype.ContextDeps], url: str) -> Any:
    """Resolve a public t.me message link to the Message object.

    Public channels are readable by any bot; groups the bot is not a member
    of, private channels and invite links raise ValueError.
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
    return message


async def _download_tme_media(ctx: RunContext[datatype.ContextDeps], url: str) -> bytes:
    """Download the media of a public t.me message link. Size-limited like
    chat://media.
    """
    message = await _get_tme_message(ctx, url)
    chat_ref, msg_id_str = _tme_message_parts(url) or ("chat", "?")
    return await _download_tg_bytes(
        ctx.deps.client, message, f"message {msg_id_str} in {chat_ref}"
    )


def _tg_image_media_type(message: Any) -> str | None:
    """The MIME type when the message's media is a still image, else None."""
    if getattr(message, "photo", None):
        return "image/jpeg"
    document = getattr(message, "document", None)
    if document is not None:
        mime = getattr(document, "mime_type", None) or ""
        base = mime.split(";")[0]
        if base.startswith("image/"):
            return base
    return None


def _run_model_accepts_images(ctx: RunContext[datatype.ContextDeps]) -> bool:
    """Whether the model serving this run can take image parts.

    The multimodal model is the main model unless a separate spec is
    configured (agent.py), so comparing the run model's name against the
    effective multimodal spec covers both setups. Conservative: per-chat
    model overrides that name-differ fall back to text markers.
    """
    if "photo" not in app_config.agent_multimodal_inputs:
        return False
    spec = app_config.agent_model_multimodal or app_config.agent_model
    if not spec:
        return False
    model_name = getattr(ctx.model, "model_name", None)
    return bool(model_name) and model_name == provider._parse_spec(spec)[1]


async def _native_image_return(
    ctx: RunContext[datatype.ContextDeps], path: str, what: str
) -> ToolReturn | None:
    """Read an image-bearing target as native BinaryContent for the model.

    Returns None when the target is not an image, the run model cannot take
    images, or the message cannot be resolved — the caller falls back to the
    text path, which owns resolution errors. Download failures raise (no
    silent double-download through the fallback path).
    """
    if not _run_model_accepts_images(ctx):
        return None
    protocol, rest = _split_target(path)
    try:
        if protocol == "chat://":
            message = await _get_chat_media_message(ctx, rest)
        elif protocol == "http":
            message = await _get_tme_message(ctx, path)
        else:
            return None
    except Exception:
        return None
    media_type = _tg_image_media_type(message)
    if media_type is None:
        return None
    data = await _download_tg_bytes(ctx.deps.client, message, what)
    caption = (getattr(message, "caption", None) or "").strip()
    text = f"[Image from {what}]" + (f"\n[Caption]: {caption}" if caption else "")
    return ToolReturn(
        return_value=text,
        content=[text, BinaryContent(data=data, media_type=media_type)],
    )
