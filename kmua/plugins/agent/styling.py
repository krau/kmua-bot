"""Markdown -> Telegram formatting converters.

Wraps telegramify-markdown and exposes three public functions:

    convert_md(text) -> tuple[str, list[pyrogram.types.MessageEntity]]
    convert_md_chunks(text, max_utf16_len=4096) -> list[tuple[str, entities]]
    convert_rich_md(text) -> list[pyrogram.types.InputRichMessage]

convert_md returns (plain_text, entities), or (original_text, []) on failure.
Entities use UTF-16 code-unit offsets as required by the Telegram Bot API.
convert_md_chunks additionally splits text that exceeds Telegram's per-message
length limit. convert_rich_md returns rich message payloads already split
within Telegram's byte/block limits, or [] when the text is empty or
conversion fails.
"""

from typing import Any, cast

import pyrogram.enums
import pyrogram.types
import telegramify_markdown
from telegramify_markdown.config import get_runtime_config

from kmua.logger import logger


def _entity_type(type_str: str) -> pyrogram.enums.MessageEntityType:
    """Map a telegramify-markdown type string to a Pyrogram enum member.

    Falls back to UNKNOWN for any unrecognised type.
    """
    try:
        return pyrogram.enums.MessageEntityType[type_str.upper()]
    except KeyError:
        return pyrogram.enums.MessageEntityType.UNKNOWN


# One-time configuration: suppress emoji heading prefixes for cleaner output
_cfg = get_runtime_config()
_cfg.markdown_symbol.heading_level_1 = ""
_cfg.markdown_symbol.heading_level_2 = ""
_cfg.markdown_symbol.heading_level_3 = ""
_cfg.markdown_symbol.heading_level_4 = ""


def _pyrogram_entities(
    tg_entities: list[Any],
) -> list[pyrogram.types.MessageEntity]:
    """Map telegramify-markdown entities to Pyrogram MessageEntity objects."""
    pyrogram_entities = []
    for e in tg_entities:
        etype = _entity_type(e.type)
        kwargs: dict[str, Any] = {
            "type": etype,
            "offset": e.offset,
            "length": e.length,
        }
        if etype == pyrogram.enums.MessageEntityType.PRE:
            kwargs["language"] = e.language if e.language is not None else ""
        if etype == pyrogram.enums.MessageEntityType.BLOCKQUOTE:
            kwargs["expandable"] = True
        if etype == pyrogram.enums.MessageEntityType.TEXT_LINK:
            kwargs["url"] = e.url
        pyrogram_entities.append(pyrogram.types.MessageEntity(**kwargs))
    return pyrogram_entities


def convert_md(
    text: str,
) -> tuple[str, list[pyrogram.types.MessageEntity]]:
    """Convert Markdown to plain text + Telegram MessageEntity list.

    Returns (plain_text, entities) on success.
    Returns (original_text, []) on any conversion error (safe fallback).

    Entities carry UTF-16 offsets and can be passed directly to Pyrogram's
    reply_text / edit_text ``entities`` parameter without setting parse_mode.
    """
    if not text:
        return text, []
    try:
        plain, tg_entities = telegramify_markdown.convert(text)
        return plain, _pyrogram_entities(tg_entities)
    except Exception as e:
        logger.debug(f"Markdown conversion failed: {e}")
        return text, []


def convert_md_chunks(
    text: str,
    max_utf16_len: int = 4096,
) -> list[tuple[str, list[pyrogram.types.MessageEntity]]]:
    """Convert Markdown to plain text + entities, split to fit Telegram.

    Only splits when the converted text exceeds ``max_utf16_len`` UTF-16 code
    units (Telegram's per-message limit); entities crossing a split are
    clipped into both chunks. Returns [] when nothing is left to send and
    falls back to a single entity-less chunk on conversion error.
    """
    if not text:
        return []
    try:
        plain, tg_entities = telegramify_markdown.convert(text)
        return [
            (chunk_text, _pyrogram_entities(chunk_entities))
            for chunk_text, chunk_entities in telegramify_markdown.split_entities(
                plain, tg_entities, max_utf16_len
            )
        ]
    except Exception as e:
        logger.debug(f"Markdown conversion failed: {e}")
        return [(text, [])] if text.strip() else []


def split_plain_text(text: str, max_utf16_len: int = 4096) -> list[str]:
    """Split already-plain text to fit Telegram's per-message limit.

    Returns [] when the text is empty or whitespace-only.
    """
    if not text.strip():
        return []
    return [
        chunk
        for chunk, _ in telegramify_markdown.split_entities(text, [], max_utf16_len)
    ]


def convert_rich_md(text: str) -> list[pyrogram.types.InputRichMessage]:
    """Convert Markdown to sendable Telegram rich message payloads.

    Headings, tables, formulas, task lists, details and inline media are kept
    as structured blocks. Output is split at Telegram's rich message limits
    (32768 bytes / 500 blocks), so long text yields several payloads to send
    in order. Returns [] when the text is empty or conversion fails.
    """
    if not text or not text.strip():
        return []
    try:
        payloads = [
            cast(telegramify_markdown.InputRichMessage, item.rich_message)
            for item in telegramify_markdown.telegramify_rich(text)
        ]
        return [
            pyrogram.types.InputRichMessage(
                html=payload.html,
                markdown=payload.markdown,
                is_rtl=payload.is_rtl,
                skip_entity_detection=payload.skip_entity_detection,
            )
            for payload in payloads
        ]
    except Exception as e:
        logger.debug(f"Rich markdown conversion failed: {e}")
        return []
