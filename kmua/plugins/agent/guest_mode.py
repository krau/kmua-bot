from __future__ import annotations

from pyrogram.client import Client as PyrogramClient
from pyrogram.raw.functions.messages.set_bot_guest_chat_result import (
    SetBotGuestChatResult,
)
from pyrogram.types import InlineQueryResultArticle, InputTextMessageContent, Message

from kmua.logger import logger
from kmua.plugins.agent import datatype
from kmua.plugins.agent.styling import convert_md

_MAX_GUEST_MESSAGE_LENGTH = 4096


async def answer_guest_query(
    client: PyrogramClient,
    message: Message,
    text: str,
    deps: datatype.ContextDeps | None = None,
) -> bool:
    """Reply to a guest chat query. Only one reply is allowed per query."""
    if deps is not None and deps.guest_replied:
        logger.debug("Guest query already replied, skipping text reply")
        return False
    query_id = message.guest_query_id
    if not query_id:
        logger.warning("answer_guest_query called without guest_query_id")
        return False

    plain, entities = convert_md(text)
    if len(plain) > _MAX_GUEST_MESSAGE_LENGTH:
        plain = plain[: _MAX_GUEST_MESSAGE_LENGTH - 3] + "..."
        entities = None

    try:
        content = InputTextMessageContent(
            message_text=plain,
            entities=entities or [],
        )
        result = InlineQueryResultArticle(
            title=".",
            input_message_content=content,
        )
        await client.invoke(
            SetBotGuestChatResult(
                query_id=int(query_id),
                result=await result.write(client),
            )
        )
        if deps is not None:
            deps.guest_replied = True
        logger.debug(
            f"Guest reply for query {query_id} in chat {message.chat.id if message.chat else '?'}: "
            f"{plain[:200]}"
        )
        return True
    except Exception as e:
        logger.error(f"Failed to answer guest query: {e.__class__.__name__} - {e}")
        return False
