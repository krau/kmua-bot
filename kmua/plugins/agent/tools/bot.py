import datetime
from dataclasses import dataclass
from typing import Any

from pydantic_ai import ModelRetry, RunContext
from pyrogram.raw.functions.messages.get_messages import (
    GetMessages as _RawGetMessages,
)
from pyrogram.raw.types.input_message_id import InputMessageID as _RawInputMessageID

from kmua import common, database
from kmua.common.tgmethod import HistoryMessage
from kmua.logger import logger
from kmua.services import btts

from .. import datatype

# Reply-chain walk limit: a real reply chain never approaches this; it only
# bounds pathological input (malformed reply loops / absurd depth). The hop
# cap also caps the returned ids: each hop adds exactly one id.
_MAX_REPLY_CHAIN_HOPS = 200


@dataclass
class ChatMessage:
    # chat_id: int
    user_id: int
    username: str | None = None
    text: str | None = None
    time: datetime.datetime | None = None


async def get_history_messages(
    ctx: RunContext[datatype.ContextDeps],
    before: int | None = None,
    after: int | None = None,
    from_id: int | None = None,
    to_id: int | None = None,
    reply_chain_of: int | None = None,
    count: int | None = None,
) -> str:
    """
    Fetch historical messages from this group.

    Pick exactly one selector:
        (nothing)          — the latest `count` messages
        before=<id>        — the `count` messages immediately before message <id>
        after=<id>         — the `count` messages immediately after message <id>
        from_id=<a>&to_id=<b> — messages <a>..<b> inclusive; ignores count, range capped at 200
        reply_chain_of=<id> — the full reply chain of message <id>, from the
            oldest ancestor to <id> itself, newest last

    Args:
        before: anchor message id; selects messages older than it.
        after: anchor message id; selects messages newer than it.
        from_id: first message id of an inclusive range (with to_id).
        to_id: last message id of an inclusive range (with from_id).
        reply_chain_of: anchor message id; returns its whole reply chain.
        count: max number of messages (1~200, default 50); only used with
            before/after selectors.

    Returns:
        Formatted message list or an error message.
    """
    chat_id = ctx.deps.chat_id
    user_id = ctx.deps.user_id

    if chat_id == user_id:
        return "This tool is not available in private chats."

    if count is None:
        count = 50
    if count <= 0 or count > 200:
        raise ModelRetry("Count must be between 1 and 200, inclusive.")

    selectors = [
        s for s in (before, after, from_id, to_id, reply_chain_of) if s is not None
    ]
    if (
        len(selectors) > 2
        or (from_id is None) != (to_id is None)
        or (reply_chain_of is not None and len(selectors) != 1)
    ):
        return (
            "Error: pick exactly one selector: before=<id>, after=<id>, "
            "from_id=<a>&to_id=<b>, or reply_chain_of=<id>."
        )

    if before is not None:
        start_id = max(1, before - count)
        end_id = before
    elif after is not None:
        start_id = after + 1
        end_id = after + 1 + count
    elif from_id is not None and to_id is not None:
        if to_id < from_id:
            return "Error: to_id must be >= from_id."
        if to_id - from_id + 1 > 200:
            return "Error: the requested range exceeds 200 messages; use a narrower from_id..to_id."
        start_id, end_id = from_id, to_id + 1
    elif reply_chain_of is not None:
        chain_ids = await _fetch_reply_chain_ids(ctx, reply_chain_of)
        if chain_ids is None:
            return "Error: message not found or has no reply chain."
        msgs = await _fetch_history_messages(chat_id, chain_ids)
        if not msgs:
            return "No messages found in the specified range."
        return await _format_history(msgs)
    else:
        current_id = ctx.deps.message.id
        if current_id is None:
            return "Error: cannot fetch latest messages; the current message ID is unknown."
        start_id = max(1, current_id - count + 1)
        end_id = current_id + 1

    msgs = await _fetch_history_messages(chat_id, list(range(start_id, end_id)))
    if not msgs:
        return "No messages found in the specified range."
    return await _format_history(msgs)


async def _fetch_reply_chain_ids(
    ctx: RunContext[datatype.ContextDeps], anchor_id: int
) -> list[int] | None:
    """The reply-chain message ids under anchor_id, oldest first, anchor last.

    Walks backwards one hop at a time: each message's reply header points at
    its direct parent, so fetch the parent by id, then the parent's parent,
    until there is no parent left (or one hop exceeds the cap). Message ids
    are globally monotonic, so the walk always terminates.
    """
    await ctx.deps.client.resolve_peer(ctx.deps.chat_id)
    r = await ctx.deps.client.invoke(
        _RawGetMessages(id=[_RawInputMessageID(id=anchor_id)])
    )
    messages = getattr(r, "messages", None) or []
    anchor = next((m for m in messages if getattr(m, "id", None) == anchor_id), None)
    if anchor is None:
        return None

    chain: dict[int, Any] = {anchor_id: anchor}
    current_id = anchor_id
    # Each hop adds exactly one id, so the cap bounds both the number of
    # fetches and the returned size (matching the tool's 200-message ceiling).
    for _ in range(_MAX_REPLY_CHAIN_HOPS):
        current = chain[current_id]
        header = getattr(current, "reply_to", None)
        reply_id = getattr(header, "reply_to_msg_id", None)
        if not reply_id:
            break
        resp = await ctx.deps.client.invoke(
            _RawGetMessages(id=[_RawInputMessageID(id=reply_id)])
        )
        ancestor = next(
            (
                m
                for m in (getattr(resp, "messages", None) or [])
                if getattr(m, "id", None) == reply_id
            ),
            None,
        )
        if ancestor is None:
            break
        chain[reply_id] = ancestor
        current_id = reply_id

    ids = sorted(chain)
    return ids


async def _fetch_history_messages(
    chat_id: int, message_ids: list[int]
) -> list[HistoryMessage]:
    """Fetch cached HistoryMessage rows for the given ids."""
    try:
        return await common.get_messages_with_cache(
            chat_id=chat_id, message_ids=message_ids, replies=1
        )
    except Exception as e:
        logger.error(f"Error fetching history messages: {e.__class__.__name__}:{e}")
        raise


async def _format_history(msgs: list[HistoryMessage]) -> str:
    """Render fetched history rows as readable text."""
    lines = [f"Chat History ({len(msgs)} messages):\n"]

    for msg in msgs:
        if not msg.user_id:
            continue

        # Get username
        user = await database.get_user_by_id(msg.user_id)
        username = user.full_name if user is not None else f"User_{msg.user_id}"

        # Format time (full datetime)
        time_str = (
            msg.time.strftime("%Y-%m-%d %H:%M:%S")
            if msg.time
            else "????-??-?? ??:??:??"
        )

        # Format message (no truncation)
        text = msg.text if msg.text else "[media/empty]"

        lines.append(f"[{time_str}]<{msg.message_id}> {username}: {text}")

    return "\n".join(lines)


async def search_messages(
    ctx: RunContext[datatype.ContextDeps],
    query: str,
    count: int = 20,
    user_id: int | None = None,
) -> str:
    """Search messages by query in the current chat.

    Arguments:
        query -- search query (required).
        user_id -- if specified, only search messages from this user.
        count -- maximum number of messages to return (default: 20).

    Returns:
        Formatted search results or error message.
    """

    if not btts.btts_client:
        return "Feature is not available."
    if count <= 0 or count > 200:
        raise ModelRetry("Count must be between 1 and 200, inclusive.")
    chat_id = int(str(ctx.deps.chat_id).removeprefix("-100"))
    resp, err = await btts.btts_client.search(
        query=query,
        chat_id=chat_id,
        limit=count,
        offset=0,
        users=str(user_id or ""),
    )
    if err != "" or resp is None:
        logger.error(f"Error searching messages: {err}")
        return "Error searching messages"
    results = resp.results
    if not results.hits:
        return "No messages found matching the query."

    # Format search results
    lines = [f"🔍 Search Results for '{query}' ({len(results.hits)} matches):\n"]

    for i, hit in enumerate(results.hits, 1):
        if hit.chat_id != chat_id:
            continue
        if user_id and hit.user_id != user_id:
            continue
        if not hit.message:
            continue

        # Get user info
        user = await database.get_user_by_id(hit.user_id)
        username = user.full_name if user is not None else f"User_{hit.user_id}"

        # Format time
        time_str = datetime.datetime.fromtimestamp(
            hit.timestamp, datetime.UTC
        ).strftime("%Y-%m-%d %H:%M:%S")

        # Format message with match highlighting
        message_text = hit.message

        lines.append(f"Result {i}:")
        lines.append(f"  [{time_str}]<{hit.id}> {username}: {message_text}")
        lines.append("")  # Empty line between results

    if len(lines) == 1:  # Only header, no results
        return "No messages found matching the query."

    return "\n".join(lines)
