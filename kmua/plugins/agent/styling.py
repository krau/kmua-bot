"""Markdown -> Telegram entities converter.

Wraps telegramify-markdown's convert() and exposes a single public function:

    convert_md(text) -> tuple[str, list[pyrogram.types.MessageEntity]]

Returns (plain_text, entities) on success, or (original_text, []) on failure.
Entities use UTF-16 code-unit offsets as required by the Telegram Bot API.
"""

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
        pyrogram_entities = []
        for e in tg_entities:
            etype = _entity_type(e.type)
            kwargs = {
                "type": etype,
                "offset": e.offset,
                "length": e.length,
            }
            if etype == pyrogram.enums.MessageEntityType.PRE or e.language is not None:
                kwargs["language"] = e.language
            if etype == pyrogram.enums.MessageEntityType.BLOCKQUOTE:
                kwargs["expandable"] = True
            if etype == pyrogram.enums.MessageEntityType.TEXT_LINK:
                kwargs["url"] = e.url
            pyrogram_entities.append(pyrogram.types.MessageEntity(**kwargs))
        return plain, pyrogram_entities
    except Exception as e:
        logger.debug(f"Markdown conversion failed: {e}")
        return text, []
