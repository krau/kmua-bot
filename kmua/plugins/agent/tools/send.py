import datetime
from dataclasses import dataclass
from hashlib import md5
from typing import Literal

import pyrogram
from pydantic_ai import ModelRetry, RunContext

from kmua import common
from kmua.logger import logger

from .. import datatype, sticker_memory, sticker_vec


@dataclass
class SendResult:
    success: bool
    message: str | None = None


async def send_media(
    ctx: RunContext[datatype.ContextDeps],
    type: Literal["photo", "video", "audio", "document"],
    text: str | None = None,
    url: str | None = None,
    caption: str | None = None,
    schedule_time: str | None = None,
) -> SendResult:
    """Send a media message to the current chat.

    **Use this tool only when a normal return value is not appropriate**, such as:
    - Sending a scheduled/delayed message (use `schedule_time`)
    - Proactively sending media (photo, video, audio, document)
    - Any situation where you need to send a non-text message type

    Args:
        type: Message type. One of "photo", "video", "audio", "document".
        url: Direct URL for media types.
        caption: Optional caption for media messages.
        schedule_time: Optional ISO 8601 datetime string to schedule delivery,
            e.g. "2025-06-04T15:00:00+08:00". If omitted, sends immediately.

    Returns:
        A SendResult indicating success or failure.
    """
    logger.debug(
        f"send_media called with type={type} for user_id={ctx.deps.user_id} in chat_id={ctx.deps.chat_id}"
    )
    if ctx.deps.message is None or ctx.deps.chat_id is None:
        return SendResult(success=False, message="Message context is unavailable.")

    schedule_datetime: datetime.datetime | None = None
    if schedule_time is not None:
        try:
            schedule_datetime = datetime.datetime.fromisoformat(schedule_time)
        except ValueError as e:
            raise ModelRetry(
                f"Invalid schedule_time format. Use ISO 8601, e.g. '2025-06-04T15:00:00+08:00'. Error: {e}"
            )
        if schedule_datetime < datetime.datetime.now(datetime.UTC):
            raise ModelRetry("schedule_time must be in the future.")

    reply_params = pyrogram.types.ReplyParameters(
        message_id=ctx.deps.message.id,
    )
    chat_id = ctx.deps.chat_id

    if schedule_datetime is not None:
        await _schedule_media(
            ctx,
            type,
            text,
            url,
            caption,
            schedule_datetime,
            chat_id,
        )
        return SendResult(
            success=True, message=f"Scheduled for {schedule_datetime.isoformat()}"
        )

    try:
        match type:
            case "photo":
                if not url:
                    raise ModelRetry("'url' is required for type 'photo'.")
                await ctx.deps.client.send_photo(
                    chat_id=chat_id,
                    photo=url,
                    caption=caption,  # type: ignore[arg-type]
                    reply_parameters=reply_params,
                )

            case "video":
                if not url:
                    raise ModelRetry("'url' is required for type 'video'.")
                await ctx.deps.client.send_video(
                    chat_id=chat_id,
                    video=url,
                    caption=caption,  # type: ignore[arg-type]
                    reply_parameters=reply_params,
                )

            case "audio":
                if not url:
                    raise ModelRetry("'url' is required for type 'audio'.")
                await ctx.deps.client.send_audio(
                    chat_id=chat_id,
                    audio=url,
                    caption=caption,  # type: ignore[arg-type]
                    reply_parameters=reply_params,
                )

            case "document":
                if not url:
                    raise ModelRetry("'url' is required for type 'document'.")
                await ctx.deps.client.send_document(
                    chat_id=chat_id,
                    document=url,
                    caption=caption,  # type: ignore[arg-type]
                    reply_parameters=reply_params,
                )

            case _:
                raise ModelRetry(
                    f"Unknown type '{type}'. Use one of: photo, video, audio, document."
                )

    except ModelRetry:
        raise
    except Exception as e:
        logger.error(f"send_media failed (type={type}): {e.__class__.__name__}: {e}")
        raise ModelRetry(f"Failed to send media: {e.__class__.__name__}: {e}")

    return SendResult(success=True)


async def _schedule_media(
    ctx: RunContext[datatype.ContextDeps],
    type: str,
    text: str | None,
    url: str | None,
    caption: str | None,
    schedule_datetime: datetime.datetime,
    chat_id: int,
) -> None:
    job_key = (
        f"agent_send_media:{chat_id}:{ctx.deps.user_id}"
        f":{schedule_datetime.timestamp()}"
        f":{md5((text or url or '').encode()).hexdigest()}"
    )

    async def _job() -> None:
        result = await send_media(
            ctx=ctx,
            type=type,  # type: ignore[arg-type]
            text=text,
            url=url,
            caption=caption,
            schedule_time=None,
        )
        if not result.success:
            logger.error(f"Scheduled send_media failed: {result.message}")

    common.jobqueue.add_onetime_job(
        job_key,
        run_date=schedule_datetime,
        func=_job,
    )


async def send_poll(
    ctx: RunContext[datatype.ContextDeps],
    question: str,
    options: list[str],
    is_anonymous: bool = False,
    allows_multiple_answers: bool = False,
    schedule_time: str | None = None,
) -> SendResult:
    """Send a poll to the current chat.

    Use this tool to create interactive polls with 2-8 options for users to vote on.

    Args:
        question: The poll question text (1-300 characters).
        options: List of 2-8 answer options for the poll.
        is_anonymous: Whether the poll is anonymous.
        allows_multiple_answers: Whether users can select multiple answers.
        schedule_time: Optional ISO 8601 datetime string to schedule delivery,
            e.g. "2025-06-04T15:00:00+08:00". If omitted, sends immediately.

    Returns:
        A SendResult indicating success or failure.
    """
    logger.debug(
        f"send_poll called for user_id={ctx.deps.user_id} in chat_id={ctx.deps.chat_id}"
    )
    if ctx.deps.message is None or ctx.deps.chat_id is None:
        return SendResult(success=False, message="Message context is unavailable.")

    schedule_datetime: datetime.datetime | None = None
    if schedule_time is not None:
        try:
            schedule_datetime = datetime.datetime.fromisoformat(schedule_time)
        except ValueError as e:
            raise ModelRetry(
                f"Invalid schedule_time format. Use ISO 8601, e.g. '2025-06-04T15:00:00+08:00'. Error: {e}"
            )
        if schedule_datetime < datetime.datetime.now(datetime.UTC):
            raise ModelRetry("schedule_time must be in the future.")

    reply_params = pyrogram.types.ReplyParameters(
        message_id=ctx.deps.message.id,
    )
    chat_id = ctx.deps.chat_id

    if not question or not question.strip():
        raise ModelRetry("'question' is required for poll.")
    if not options or len(options) < 2:
        raise ModelRetry("'options' must have at least 2 items.")
    if len(options) > 10:
        raise ModelRetry("'options' must have at most 10 items.")

    if schedule_datetime is not None:
        await _schedule_poll(
            ctx,
            question,
            options,
            is_anonymous,
            allows_multiple_answers,
            schedule_datetime,
            reply_params,
            chat_id,
        )
        return SendResult(
            success=True, message=f"Scheduled for {schedule_datetime.isoformat()}"
        )

    try:
        await ctx.deps.client.send_poll(
            chat_id=chat_id,
            question=question,
            options=options,
            is_anonymous=is_anonymous,
            allows_multiple_answers=allows_multiple_answers,
            reply_parameters=reply_params,
        )
    except Exception as e:
        logger.error(f"send_poll failed: {e.__class__.__name__}: {e}")
        raise ModelRetry(f"Failed to send poll: {e.__class__.__name__}: {e}")

    return SendResult(success=True)


async def _schedule_poll(
    ctx: RunContext[datatype.ContextDeps],
    question: str,
    options: list[str],
    is_anonymous: bool,
    allows_multiple_answers: bool,
    schedule_datetime: datetime.datetime,
    chat_id: int,
) -> None:
    job_key = (
        f"agent_send_poll:{chat_id}:{ctx.deps.user_id}"
        f":{schedule_datetime.timestamp()}"
        f":{md5(question.encode()).hexdigest()}"
    )

    async def _job() -> None:
        result = await send_poll(
            ctx=ctx,
            question=question,
            options=options,
            is_anonymous=is_anonymous,
            allows_multiple_answers=allows_multiple_answers,
            schedule_time=None,
        )
        if not result.success:
            logger.error(f"Scheduled send_poll failed: {result.message}")

    common.jobqueue.add_onetime_job(
        job_key,
        run_date=schedule_datetime,
        func=_job,
    )


async def send_sticker(
    ctx: RunContext[datatype.ContextDeps],
    query: str,
) -> SendResult:
    """Search for a semantically matching sticker from this group's sticker memory and send it.

    Args:
        query: Natural language description of the desired sticker, e.g. "happy excited cat",
               "sad crying", "thumbs up approval".
        k: How many candidates to retrieve; the closest match is sent. Default 1.

    Returns:
        A SendResult indicating success or failure.
    """
    if ctx.deps.chat_id is None or ctx.deps.message is None:
        return SendResult(success=False, message="Message context is unavailable.")

    if sticker_memory.embedder is None:
        return SendResult(success=False, message="Sticker memory is not configured.")

    embedding = await sticker_memory.get_embedding(query)
    if embedding is None:
        raise ModelRetry("Failed to embed query.")

    results = await sticker_vec.search(ctx.deps.chat_id, embedding, k=1)
    if not results:
        raise ModelRetry("No matching sticker found in this group's sticker memory.")

    file_id, description, distance = results[0]
    logger.debug(
        f"send_sticker: query={query!r} -> description={description!r} distance={distance:.4f}"
    )
    try:
        await ctx.deps.client.send_sticker(
            chat_id=ctx.deps.chat_id,
            sticker=file_id,
            reply_parameters=pyrogram.types.ReplyParameters(
                message_id=ctx.deps.message.id,
            ),
        )
    except Exception as e:
        logger.error(f"send_sticker send error: {e.__class__.__name__}: {e}")
        raise ModelRetry(f"Failed to send sticker: {e.__class__.__name__}: {e}")

    return SendResult(success=True, message=f"Sent sticker: {description}")


async def send_reaction(
    ctx: RunContext[datatype.ContextDeps],
    emoji: str,
) -> SendResult:
    """Send a reaction (emoji) to the user's message.

    Args:
        emoji: The emoji to react with, e.g. "🥰", "❤️", "😡".

    Returns:
        A SendResult indicating success or failure.
    """
    if ctx.deps.message is None:
        return SendResult(success=False, message="Message context is unavailable.")
    try:
        await ctx.deps.client.send_reaction(
            chat_id=ctx.deps.chat_id,
            message_id=ctx.deps.message.id,
            emoji=emoji,
        )
    except Exception as e:
        logger.error(f"send_reaction error: {e.__class__.__name__}: {e}")
        raise ModelRetry(f"Failed to send reaction: {e.__class__.__name__}: {e}")
    return SendResult(success=True)


__all__ = ["send_media", "send_poll", "send_reaction", "send_sticker"]
