import datetime
from dataclasses import dataclass
from hashlib import md5
from typing import Literal

import pyrogram
import pyrogram.errors
from pydantic_ai import ModelRetry, RunContext

from kmua import common
from kmua.logger import logger

from .. import datatype, sticker_memory, sticker_vec


@dataclass
class SendResult:
    success: bool
    message: str | None = None

    def text(self) -> str:
        if self.success:
            msg = "发送成功"
            if self.message:
                msg = f"{msg}, 提示信息: {self.message}"
            return msg
        msg = "发送失败"
        if self.message:
            msg = f"{msg}, 错误信息: {self.message}"
        return msg


async def send_media(
    ctx: RunContext[datatype.ContextDeps],
    type: Literal["photo", "video", "audio", "document"],
    text: str | None = None,
    url: str | None = None,
    caption: str | None = None,
    schedule_time: str | None = None,
) -> str:
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
    if ctx.deps.message is None or ctx.deps.chat_id is None:
        return SendResult(
            success=False, message="Message context is unavailable."
        ).text()

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
        ).text()

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

    return SendResult(success=True).text()


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
        logger.info(f"Scheduled send_media result: {result}")

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
) -> str:
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
    if ctx.deps.message is None or ctx.deps.chat_id is None:
        return SendResult(
            success=False, message="Message context is unavailable."
        ).text()

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
            chat_id,
        )
        return SendResult(
            success=True, message=f"Scheduled for {schedule_datetime.isoformat()}"
        ).text()

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

    return SendResult(success=True).text()


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
        logger.info(f"Scheduled send_poll result: {result}")

    common.jobqueue.add_onetime_job(
        job_key,
        run_date=schedule_datetime,
        func=_job,
    )


async def send_sticker(
    ctx: RunContext[datatype.ContextDeps],
    query: str,
) -> str:
    """Search for a semantically matching sticker and send it.

    Args:
        query: Natural language description of the desired sticker, e.g. "happy excited",
               "sad crying", "thumbs up approval".
        k: How many candidates to retrieve; the closest match is sent. Default 1.

    Returns:
        A SendResult indicating success or failure.
    """
    if ctx.deps.chat_id is None or ctx.deps.message is None:
        return SendResult(
            success=False, message="Message context is unavailable."
        ).text()

    if sticker_memory.embedder is None:
        return SendResult(
            success=False, message="Sticker memory is not configured."
        ).text()

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

    return SendResult(success=True).text()


async def send_reaction(
    ctx: RunContext[datatype.ContextDeps],
    emoji: str,
) -> str:
    """Send a reaction (emoji) to the user's message.

    Args:
        emoji: The emoji to react with, e.g. "🥰", "❤️", "😡".

    Returns:
        A SendResult indicating success or failure.
    """
    if ctx.deps.message is None:
        return SendResult(
            success=False, message="Message context is unavailable."
        ).text()
    try:
        await ctx.deps.client.send_reaction(
            chat_id=ctx.deps.chat_id,
            message_id=ctx.deps.message.id,
            emoji=emoji,
        )
    except pyrogram.errors.exceptions.bad_request_400.ReactionInvalid:
        chat = await common.get_chat_full(ctx.deps.client, ctx.deps.chat_id)
        if chat and chat.available_reactions and chat.available_reactions.reactions:
            emojis = [
                r.emoji
                for r in chat.available_reactions.reactions
                if r.emoji is not None
            ]
            raise ModelRetry(
                f"Invalid reaction emoji. This chat supports the following reactions: {', '.join(emojis)}"
            )
        raise ModelRetry("Invalid reaction emoji, try another one.")
    except Exception as e:
        logger.error(f"send_reaction error: {e.__class__.__name__}: {e}")
        raise ModelRetry(f"Failed to send reaction: {e.__class__.__name__}: {e}")
    return SendResult(success=True).text()


async def send_text(
    ctx: RunContext[datatype.ContextDeps],
    text: str,
    reply_to_message_id: int | None = None,
    schedule_time: str | None = None,
) -> str:
    """Send a plain-text message to the current chat.

    **Do NOT use this tool to reply to the user's message in a normal turn.**
    Just return the text directly as your output instead — it is faster and cleaner.

    Only call this tool when you need to:
    - Send **additional** messages beyond your main reply (e.g. a follow-up or
      a separate message after sending media).
    - Schedule a **delayed** message via `schedule_time`.

    Args:
        text: The message text to send.
        reply_to_message_id: Optional message ID to reply to. If omitted, sends as a new message.
        schedule_time: Optional ISO 8601 datetime string for delayed delivery,
            e.g. "2025-06-04T15:00:00+08:00". If omitted, sends immediately.

    Returns:
        A SendResult indicating success or failure.
    """
    if ctx.deps.message is None or ctx.deps.chat_id is None:
        return SendResult(
            success=False, message="Message context is unavailable."
        ).text()

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

    chat_id = ctx.deps.chat_id
    reply_params = (
        pyrogram.types.ReplyParameters(message_id=reply_to_message_id)
        if reply_to_message_id
        else None
    )

    if schedule_datetime is not None:
        job_key = (
            f"agent_send_text:{chat_id}:{ctx.deps.user_id}"
            f":{schedule_datetime.timestamp()}"
            f":{md5(text.encode()).hexdigest()}"
        )

        async def _job() -> None:
            try:
                await ctx.deps.client.send_message(
                    chat_id=chat_id, text=text, reply_parameters=reply_params
                )
            except Exception as e:
                logger.error(f"Scheduled send_text failed: {e.__class__.__name__}: {e}")

        common.jobqueue.add_onetime_job(job_key, run_date=schedule_datetime, func=_job)
        return SendResult(
            success=True, message=f"Scheduled for {schedule_datetime.isoformat()}"
        ).text()

    try:
        await ctx.deps.client.send_message(
            chat_id=chat_id,
            text=text,
            reply_parameters=reply_params,
        )
    except Exception as e:
        logger.error(f"send_text failed: {e.__class__.__name__}: {e}")
        raise ModelRetry(f"Failed to send text: {e.__class__.__name__}: {e}")

    return SendResult(success=True).text()


__all__ = ["send_media", "send_poll", "send_reaction", "send_sticker", "send_text"]
