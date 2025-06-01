import datetime
import random
from dataclasses import dataclass
from hashlib import md5
from typing import Literal

import pyrogram
from pydantic_ai import ModelRetry, RunContext

from kmua import common, database, i18n
from kmua.config import app_config
from kmua.logger import logger
from kmua.plugins.manyacg import manyacg

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


async def get_and_send_a_anime_photo(
    ctx: RunContext[datatype.ContextDeps],
    keyword: str = "",
) -> AnimePhotoInfo | str:
    """Get and send a random anime photo (some users call it setu/涩图).

    Args:
        keyword: Optional keyword to search for specific anime photos, max length is 100 characters.

    Returns:
        An AnimePhotoInfo object if successful, or an error message string.
    """
    logger.debug(
        f"get_and_send_a_anime_photo called with chat_id: {ctx.deps.chat_id}, user_id: {ctx.deps.user_id}, keyword: {keyword}"
    )
    if ctx.deps.message is None or ctx.deps.message.id is None:
        return "Message ID is required to reply with the photo."
    if (
        ctx.deps.chat_id is not None
        and ctx.deps.chat_id != ctx.deps.user_id
        and not (await database.get_chat_config(ctx.deps.chat_id)).setu_enabled
    ):
        return "Feature is disabled by group administrator."
    try:
        user_config = await database.get_user_config(ctx.deps.user_id)
        lang = user_config.lang
        params = {
            "r18": 2,
            "page_size": 1,
            "hybrid": app_config.manyacg_hybrid_search,
        }
        if keyword:
            params["keyword"] = keyword
        resp = await manyacg.httpx_client.get(
            url="/artwork/list",
            params=params,
        )
        if resp.status_code != 200:
            return f"Api request failed with code: {resp.status_code}"
        artwork: dict = resp.json()["data"][0]
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
        return AnimePhotoInfo(
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
        )
    except Exception as e:
        logger.error(f"get_and_send_a_anime_photo error: {e.__class__.__name__}:{e}")
        return e.__class__.__name__


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
) -> list[ChatMessage] | str:
    """
    Fetch historical messages from chat.

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
        A list of ChatMessage or error string.
    """

    if count <= 0 or count > 200:
        raise ModelRetry("Count must be between 1 and 200, inclusive.")

    chat_id = ctx.deps.chat_id
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
            return "Missing anchor_id for direction 'after'."
        start_id = anchor_id + 1
        end_id = anchor_id + 1 + count

    elif direction == "between":
        if start_id is None or end_id is None:
            return "Both start_id and end_id are required for 'between'."
        if end_id <= start_id:
            return "end_id must be greater than start_id."
        if end_id - start_id > 200:
            return "Maximum allowed range is 200 messages."
    else:
        return f"Invalid direction: {direction}"

    logger.debug(
        f"get_history_messages called: direction={direction}, start_id={start_id}, end_id={end_id}, chat_id={chat_id}"
    )
    msgs = await common.get_messages_with_cache(
        chat_id=chat_id, message_ids=list(range(start_id, end_id)), replies=1
    )
    return [
        ChatMessage(
            user_id=msg.user_id,
            username=(await database.get_user_by_id(msg.user_id)).full_name
            if msg.user_id
            else None,
            text=msg.text,
            time=msg.time,
        )
        for msg in msgs
    ]


async def schedule_message(
    ctx: RunContext[datatype.ContextDeps],
    message: str,
    schedule_time: datetime.datetime,
):
    """Schedule a message to be sent at a specific time,
    can be used to send reminders or scheduled announcements.

    Arguments:
        message: text message to be sent.
        schedule_time: datetime when the message should be sent.
    """
    logger.debug(
        f"schedule_message called with chat_id: {ctx.deps.chat_id}, user_id: {ctx.deps.user_id}, message: {message}, schedule_time: {schedule_time}"
    )
    if schedule_time < datetime.datetime.now():
        raise ModelRetry("Schedule time must be in the future.")

    async def _send_scheduled_message():
        try:
            await ctx.deps.message.reply(text=message)
        except Exception as e:
            logger.error(
                f"Failed to send scheduled message: {e.__class__.__name__}:{e}"
            )

    common.jobqueue.add_onetime_job(
        f"agent_schedule_message:{ctx.deps.chat_id}:{ctx.deps.user_id}:{schedule_time.timestamp()}:{md5(message.encode()).hexdigest()}",
        run_date=schedule_time,
        func=_send_scheduled_message,
    )
