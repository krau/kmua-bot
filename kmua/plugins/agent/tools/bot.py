import datetime
import random
from dataclasses import dataclass

import pyrogram
from pydantic_ai import ModelRetry, RunContext

import kmua.plugins
import kmua.plugins.manyacg
import kmua.plugins.manyacg.manyacg
from kmua import common, database, i18n
from kmua.config import app_config
from kmua.logger import logger

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
) -> AnimePhotoInfo | str:
    """Get and send a random anime photo (some users call it setu/涩图).

    Returns:
        An AnimePhotoInfo object if successful, or an error message string.
    """
    logger.debug(
        f"get_and_send_a_anime_photo called with chat_id: {ctx.deps.chat_id}, user_id: {ctx.deps.user_id}"
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
        resp = await kmua.plugins.manyacg.manyacg.httpx_client.get(
            url="/artwork/random", params={"r18": 2}
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
class HistoryMessage:
    user_id: int
    chat_id: int
    text: str | None = None
    time: datetime.datetime | None = None


def _chat_message_key(chat_id: int, message_id: int) -> str:
    return f"chat_history:{chat_id}:{message_id}"


async def get_latest_messages(
    ctx: RunContext[datatype.ContextDeps], count: int = 50
) -> list[HistoryMessage] | str:
    """Get latest messages in the chat, you can try using this tool if you missing some context.

    Args:
        count: (int) Number of messages to fetch, must be between 1 and 200, inclusive.

    Returns:
        List of latest messages, or error string if failed.
    """
    logger.debug(
        f"get_latest_messages called with chat_id: {ctx.deps.chat_id}, user_id: {ctx.deps.user_id}, message_id: {ctx.deps.message.id}, count: {count}"
    )
    client = ctx.deps.client
    current_message_id = ctx.deps.message.id if ctx.deps.message else None
    if current_message_id is None:
        return "Current message ID is None, cannot fetch history."
    if count <= 0 or count > 200:
        raise ModelRetry("Count must be between 1 and 200, inclusive.")

    chat_id = ctx.deps.chat_id
    message_ids_to_fetch = []
    cached_messages = {}

    start_id = max(1, current_message_id - count + 1)
    end_id = current_message_id + 1

    for i in range(start_id, end_id):
        cached_msg = await common.memttlcache.get(_chat_message_key(chat_id, i), None)
        if cached_msg is None:
            message_ids_to_fetch.append(i)
        else:
            cached_messages[i] = cached_msg

    new_messages = []
    if message_ids_to_fetch:
        msgs = await client.get_messages(
            chat_id=ctx.deps.chat_id, message_ids=message_ids_to_fetch, replies=1
        )

        if isinstance(msgs, pyrogram.types.Message):
            msgs = [msgs]

        for msg in msgs:
            if msg and msg.from_user and (msg.text or msg.caption):
                history_msg = HistoryMessage(
                    user_id=(msg.sender_chat or msg.from_user).id,
                    chat_id=msg.chat.id if msg.chat else 0,
                    text=msg.text or msg.caption,
                    time=msg.date,
                )
                new_messages.append(history_msg)

                await common.memttlcache.set(
                    _chat_message_key(chat_id, msg.id), history_msg, ttl=86400
                )

    all_messages: list[HistoryMessage] = list(cached_messages.values()) + new_messages

    all_messages.sort(key=lambda msg: 0 if msg.time is None else msg.time.timestamp())

    return all_messages
