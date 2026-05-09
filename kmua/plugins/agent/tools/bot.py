import datetime
from dataclasses import dataclass
from typing import Literal

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
    direction: Literal["latest", "before", "after", "between"] = "latest",
    count: int = 50,
    anchor_id: int | None = None,
    start_id: int | None = None,
    end_id: int | None = None,
) -> str:
    """
    Fetch historical messages from chat, can not be used in private chats.

    Args:
        direction:
            - "latest": fetch latest messages;
            - "before": messages before anchor_id;
            - "after": messages after anchor_id;
            - "between": messages from start_id to end_id (inclusive of start, exclusive of end).
        count: max number of messages to fetch (1~200).
        anchor_id: used for "before"/"after" directions, usually can be the current message ID or reply to message ID.
        start_id: starting message ID (for "between" mode).
        end_id: ending message ID (for "between" mode).

    Returns:
        Formatted string of chat history or error message.
    """
    chat_id = ctx.deps.chat_id
    user_id = ctx.deps.user_id

    if chat_id == user_id:
        return "This tool is not available in private chats."

    if count <= 0 or count > 200:
        raise ModelRetry("Count must be between 1 and 200, inclusive.")

    current_id = ctx.deps.message.id

    if direction == "latest":
        if current_id is None:
            return "Cannot fetch latest messages: current message ID is unknown."
        start_id = max(1, current_id - count + 1)
        end_id = current_id + 1

    elif direction == "before":
        if anchor_id is None:
            return "Missing anchor_id for direction 'before'."
        start_id = max(1, anchor_id - count)
        end_id = anchor_id

    elif direction == "after":
        if anchor_id is None:
            raise ModelRetry("Missing anchor_id for direction 'after'.")
        start_id = anchor_id + 1
        end_id = anchor_id + 1 + count

    elif direction == "between":
        if start_id is None or end_id is None:
            raise ModelRetry("Both start_id and end_id are required for 'between'.")
        if end_id <= start_id:
            raise ModelRetry("end_id must be greater than start_id.")
        if end_id - start_id > 200:
            raise ModelRetry("Maximum allowed range is 200 messages.")
    else:
        raise ModelRetry(
            "Invalid direction. Use 'latest', 'before', 'after', or 'between'."
        )
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
