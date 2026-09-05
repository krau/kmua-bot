import datetime
from dataclasses import dataclass

from pydantic_ai import ModelRetry, RunContext

from kmua import common, database
from kmua.logger import logger
from kmua.services import btts

from .. import datatype


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
    count: int | None = None,
) -> str:
    """
    Fetch historical messages from this group.

    Pick exactly one selector:
        (nothing)          — the latest `count` messages
        before=<id>        — the `count` messages immediately before message <id>
        after=<id>         — the `count` messages immediately after message <id>
        from_id=<a>&to_id=<b> — messages <a>..<b> inclusive; ignores count, range capped at 200

    Args:
        before: anchor message id; selects messages older than it.
        after: anchor message id; selects messages newer than it.
        from_id: first message id of an inclusive range (with to_id).
        to_id: last message id of an inclusive range (with from_id).
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

    selectors = [s for s in (before, after, from_id, to_id) if s is not None]
    if len(selectors) > 2 or (from_id is None) != (to_id is None):
        return (
            "Error: pick exactly one selector: before=<id>, after=<id>, "
            "or from_id=<a>&to_id=<b>."
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
    else:
        current_id = ctx.deps.message.id
        if current_id is None:
            return "Error: cannot fetch latest messages; the current message ID is unknown."
        start_id = max(1, current_id - count + 1)
        end_id = current_id + 1

    try:
        msgs = await common.get_messages_with_cache(
            chat_id=chat_id, message_ids=list(range(start_id, end_id)), replies=1
        )

        if not msgs:
            return "No messages found in the specified range."

        # Format messages as readable text
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
    except Exception as e:
        logger.error(f"Error fetching history messages: {e.__class__.__name__}:{e}")
        return f"Error fetching history messages: {e.__class__.__name__}"


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
