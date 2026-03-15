import datetime
import random
from dataclasses import dataclass
from typing import Literal

import pyrogram
from pydantic_ai import ModelRetry, RunContext

from kmua import common, database, i18n
from kmua.config import app_config
from kmua.logger import logger
from kmua.plugins.manyacg import manyacg
from kmua.services import btts

from .. import datatype


@dataclass
class Artist:
    name: str
    type: str
    username: str
    uid: str


@dataclass
class AnimePhotoInfo:
    title: str
    source_url: str
    r18: bool
    description: str | None = None
    artist: Artist | None = None
    tags: list[str] | None = None


@dataclass
class AnimePhotoResult:
    success: bool = True
    message: str | None = None
    data: AnimePhotoInfo | None = None


async def send_anime_photo(
    ctx: RunContext[datatype.ContextDeps], keyword: str = ""
) -> AnimePhotoResult:
    """Get and send anime photos (or called it setu/涩图).

    Args:
        keyword: Optional keyword to search for specific anime photos.

    Returns:
        An AnimePhotoResult dataclass containing the result of the operation.
    """
    if ctx.deps.message is None or ctx.deps.message.id is None:
        return AnimePhotoResult(
            success=False, message="Current message context is unavailable."
        )
    if (
        ctx.deps.chat_id is not None
        and ctx.deps.chat_id != ctx.deps.user_id
        and not (await database.get_chat_config(ctx.deps.chat_id)).setu_enabled
    ):
        return AnimePhotoResult(
            success=False, message="Anime photo feature is disabled in this chat."
        )
    try:
        ratekey = f"anime_photo_rate_limit:{ctx.deps.chat_id}:{ctx.deps.user_id}"
        if await common.memttlcache.get(ratekey, 0) > 3:
            return AnimePhotoResult(
                success=False,
                message="You are sending requests too frequently. Please try again later.",
            )
        current_count = await common.memttlcache.get(ratekey, 0)
        await common.memttlcache.set(ratekey, current_count + 1, ttl=10)
        user_config = await database.get_user_config(ctx.deps.user_id)
        lang = user_config.lang
        if keyword:
            params = {
                "r18": 2,
                "hybrid": app_config.manyacg_hybrid_search,
                "keyword": keyword,
            }
            resp = await manyacg.httpx_client.get(
                url="/artwork/list",
                params=params,
            )
        else:
            resp = await manyacg.httpx_client.get(
                url="/artwork/random",
                params={"r18": 2},
            )
        if resp.status_code != 200:
            return AnimePhotoResult(
                success=False,
                message=f"API request failed with code: {resp.status_code}",
            )
        artwork: dict = random.choice(resp.json()["data"])
        picture: dict = artwork["pictures"][
            random.randint(0, len(artwork["pictures"]) - 1)
        ]
        detail_link = (
            f"https://t.me/{app_config.manyacg_channel}/{picture['message_id']}"
            if picture.get("message_id")
            else artwork["source_url"]
        )
        await ctx.deps.client.send_photo(
            chat_id=ctx.deps.chat_id,
            photo=picture["regular"],
            caption=f"<a href='{artwork['source_url']}'>{artwork['title']}</a>",
            parse_mode=pyrogram.enums.ParseMode.HTML,
            reply_markup=pyrogram.types.InlineKeyboardMarkup(
                [
                    [
                        pyrogram.types.InlineKeyboardButton(
                            text=i18n.t("bot.button.manyacg.detail", locale=lang),
                            url=detail_link,
                        ),
                        pyrogram.types.InlineKeyboardButton(
                            text=i18n.t("bot.button.manyacg.original", locale=lang),
                            url=f"https://t.me/{app_config.manyacg_bot}/?start=file_{picture['id']}",
                        ),
                    ]
                ]
            ),
            has_spoiler=artwork["r18"],
            reply_parameters=pyrogram.types.ReplyParameters(
                message_id=ctx.deps.message.id,
            ),
        )
        return AnimePhotoResult(
            success=True,
            data=AnimePhotoInfo(
                title=artwork["title"],
                source_url=artwork["source_url"],
                r18=artwork["r18"],
                description=artwork.get("description", "")[:512],
                artist=Artist(
                    name=artwork.get("artist", {}).get("name", ""),
                    type=artwork["artist"].get("type", ""),
                    username=artwork["artist"].get("username", ""),
                    uid=artwork["artist"].get("uid", ""),
                ),
                tags=artwork.get("tags", [])[:10],
            ),
        )
    except Exception as e:
        logger.error(f"get_and_send_a_anime_photo error: {e.__class__.__name__}:{e}")
        return AnimePhotoResult(
            success=False,
            message=f"Error occurred: {e.__class__.__name__}",
        )


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
