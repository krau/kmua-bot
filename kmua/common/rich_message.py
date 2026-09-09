"""Sending Telegram rich messages (Bot API 10.1 / MTProto layer 228+).

Pyrogram's high-level ``Client.send_rich_message`` mis-parses the
``UpdateShortSentMessage`` reply for channel peers (it reads ``peer.chat_id``
on an ``InputPeerChannel``), so rich messages are sent through the raw
``messages.SendMessage`` call here instead.

A rich message has no ``Message.text``: its content lives in structured
blocks. ``message_plain_text`` renders those blocks back to text so history,
reply chains and prompts keep working for rich messages.
"""

from __future__ import annotations

import re
from html import unescape

import pyrogram
from pyrogram import utils
from pyrogram.client import Client
from pyrogram.raw.base.input_rich_message import (
    InputRichMessage as _RawInputRichMessage,
)
from pyrogram.raw.base.reply_markup import ReplyMarkup as _RawReplyMarkup
from pyrogram.raw.functions.messages.send_message import SendMessage as _RawSendMessage
from pyrogram.raw.types.update_message_id import UpdateMessageID as _RawUpdateMessageID
from pyrogram.raw.types.update_new_channel_message import (
    UpdateNewChannelMessage as _RawUpdateNewChannelMessage,
)
from pyrogram.raw.types.update_new_message import (
    UpdateNewMessage as _RawUpdateNewMessage,
)
from pyrogram.raw.types.update_short_sent_message import (
    UpdateShortSentMessage as _RawUpdateShortSentMessage,
)

__all__ = [
    "message_plain_text",
    "rich_html_plain_text",
    "rich_message_plain_text",
    "send_rich_message",
    "sent_message_id",
]

# Tags telegramify-markdown emits in rich HTML mode.
_RICH_BREAK_RE = re.compile(r"<br\s*/?>|<hr\s*/?>", re.IGNORECASE)
_RICH_BLOCK_END_RE = re.compile(
    r"</(?:p|h[1-6]|li|tr|blockquote|pre|details|summary|table|ul|ol)>", re.IGNORECASE
)
_RICH_TAG_RE = re.compile(r"<[^>]+>")
_RICH_BLANK_LINES_RE = re.compile(r"\n{3,}")


def rich_html_plain_text(html_text: str) -> str:
    """Plain text of a rich HTML payload, formatting dropped.

    Used to deliver content that could not be sent as a rich message; it
    handles the tag set telegramify-markdown emits, not arbitrary HTML.
    """
    if not html_text:
        return ""
    text = _RICH_BREAK_RE.sub("\n", html_text)
    text = _RICH_BLOCK_END_RE.sub("\n", text)
    text = _RICH_TAG_RE.sub("", text)
    text = unescape(text)
    return _RICH_BLANK_LINES_RE.sub("\n\n", text).strip()


def sent_message_id(result: object) -> int | None:
    """Message id carried by a ``messages.SendMessage`` reply, if any."""
    if isinstance(result, _RawUpdateShortSentMessage):
        return result.id
    for update in getattr(result, "updates", None) or ():
        if isinstance(update, _RawUpdateMessageID):
            return update.id
        if isinstance(update, (_RawUpdateNewMessage, _RawUpdateNewChannelMessage)):
            message = getattr(update, "message", None)
            if message is not None:
                return message.id
    return None


def _rich_text_plain(value: object) -> str:
    """Render a RichText tree (str / list / wrapper objects) to plain text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "".join(_rich_text_plain(item) for item in value)
    expression = getattr(value, "expression", None)
    if isinstance(expression, str):
        return expression
    alternative = getattr(value, "alternative_text", None)
    text = getattr(value, "text", None)
    if text is not None:
        return _rich_text_plain(text)
    if isinstance(alternative, str):
        return alternative
    return ""


def _rich_block_plain(block: object) -> str:
    """Render one RichBlock (and its nested blocks) to plain text."""
    if isinstance(block, pyrogram.types.RichBlockListItem):
        prefix = ""
        if block.is_checked is not None:
            prefix = "✅ " if block.is_checked else "☑ "
        elif block.label:
            prefix = f"{block.label} "
        return prefix + " ".join(
            part for part in (_rich_block_plain(item) for item in block.blocks) if part
        )
    if isinstance(block, pyrogram.types.RichBlockTable):
        return "\n".join(
            " | ".join(_rich_text_plain(cell.text) for cell in row)
            for row in block.cells
        )
    parts: list[str] = []
    expression = getattr(block, "expression", None)
    if isinstance(expression, str):
        parts.append(expression)
    for attr in ("summary", "text", "caption"):
        value = getattr(block, attr, None)
        if value is not None:
            parts.append(_rich_text_plain(value))
    for attr in ("items", "blocks"):
        nested = getattr(block, attr, None)
        if nested:
            parts.extend(_rich_block_plain(child) for child in nested)
    return "\n".join(part for part in parts if part)


def rich_message_plain_text(rich_message: pyrogram.types.RichMessage) -> str:
    """Best-effort plain text of a rich message, block per line."""
    return "\n".join(
        part
        for part in (_rich_block_plain(block) for block in rich_message.blocks)
        if part
    )


def message_plain_text(message: pyrogram.types.Message) -> str:
    """Message text or caption, falling back to its rich message content."""
    text = message.text or message.caption
    if text:
        return text
    rich_message = getattr(message, "rich_message", None)
    if rich_message is None:
        return ""
    return rich_message_plain_text(rich_message)


async def send_rich_message(
    client: Client,
    chat_id: int | str,
    rich_message: _RawInputRichMessage,
    *,
    reply_parameters: pyrogram.types.ReplyParameters | None = None,
    message_thread_id: int | None = None,
    direct_messages_topic_id: int | None = None,
    reply_markup: _RawReplyMarkup | None = None,
) -> int | None:
    """Send one rich message, returning the id of the sent message.

    ``rich_message`` is a written raw payload (``InputRichMessageHTML``,
    ``InputRichMessageMarkdown`` or a block-based ``InputRichMessage``).
    """
    peer = await client.resolve_peer(chat_id)
    if peer is None:
        raise ValueError(f"Cannot resolve peer for chat {chat_id}")
    result = await client.invoke(
        _RawSendMessage(
            peer=peer,
            message="",
            random_id=client.rnd_id(),
            reply_to=await utils.get_reply_to(
                client, reply_parameters, message_thread_id, direct_messages_topic_id
            ),
            rich_message=rich_message,
            reply_markup=reply_markup,
        )
    )
    return sent_message_id(result)
