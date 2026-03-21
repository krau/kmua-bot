import datetime
from dataclasses import dataclass
from hashlib import md5
from typing import Literal

import pyrogram
import pyrogram.errors
from pydantic_ai import ModelRetry, RunContext

from kmua import common
from kmua.bot.client import client
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


# Module-level job functions for APScheduler persistence
# These are defined at module level so they can be serialized by reference


async def _scheduled_text_job(chat_id: int, text: str) -> None:
    """Module-level function to send scheduled text message.

    Args:
        chat_id: Target chat ID
        text: Message text to send
    """
    try:
        await client.send_message(chat_id=chat_id, text=text)
        logger.info("Scheduled text message sent successfully")
    except Exception as e:
        logger.error(f"Scheduled text message failed: {e.__class__.__name__}: {e}")


async def _scheduled_media_job(
    chat_id: int,
    media_type: Literal["photo", "video", "audio", "document"],
    media_url: str,
    caption: str,
) -> None:
    """Module-level function to send scheduled media message.

    Args:
        chat_id: Target chat ID
        media_type: Type of media
        media_url: Media URL
        caption: Media caption
    """
    try:
        match media_type:
            case "photo":
                await client.send_photo(
                    chat_id=chat_id,
                    photo=media_url,
                    caption=caption,
                )
            case "video":
                await client.send_video(
                    chat_id=chat_id,
                    video=media_url,
                    caption=caption,
                )
            case "audio":
                await client.send_audio(
                    chat_id=chat_id,
                    audio=media_url,
                    caption=caption,
                )
            case "document":
                await client.send_document(
                    chat_id=chat_id,
                    document=media_url,
                    caption=caption,
                )
        logger.info(f"Scheduled {media_type} message sent successfully")
    except Exception as e:
        logger.error(
            f"Scheduled {media_type} message failed: {e.__class__.__name__}: {e}"
        )


async def _scheduled_poll_job(
    chat_id: int,
    question: str,
    options: list[str],
    is_anonymous: bool,
    allows_multiple_answers: bool,
) -> None:
    """Module-level function to send scheduled poll.

    Args:
        chat_id: Target chat ID
        question: Poll question
        options: Poll options
        is_anonymous: Whether the poll is anonymous
        allows_multiple_answers: Whether multiple answers are allowed
    """
    try:
        from kmua.bot.client import client

        await client.send_poll(
            chat_id=chat_id,
            question=question,
            options=options,
            is_anonymous=is_anonymous,
            allows_multiple_answers=allows_multiple_answers,
        )
        logger.info(f"Scheduled poll sent successfully: {question[:30]}...")
    except Exception as e:
        logger.error(f"Scheduled poll failed: {e.__class__.__name__}: {e}")


async def schedule_message(
    ctx: RunContext[datatype.ContextDeps],
    schedule_time: str | None,
    send_immediately: bool = False,
    text: str | None = None,
    media_type: Literal["photo", "video", "audio", "document"] | None = None,
    media_url: str | None = None,
    caption: str | None = None,
) -> str:
    """Schedule a message to be sent at a specific time.

    Use this tool to schedule delayed messages (text or media) for future delivery.

    Args:
        schedule_time: ISO 8601 datetime string for scheduled delivery,
            e.g. "2025-06-04T15:00:00+08:00". Must be in the future.
        send_immediately: If True, send the message immediately.
        text: The message text to send (for text messages). Either text or media
            must be provided, but not both.
        media_type: Media type for media messages. One of "photo", "video",
            "audio", "document". Required if media_url is provided.
        media_url: Direct URL for media types. Required if media_type is provided.
        caption: Optional caption for media messages.

    Returns:
        A SendResult indicating success or failure.
    """
    if ctx.deps.message is None or ctx.deps.chat_id is None:
        return SendResult(
            success=False, message="Message context is unavailable."
        ).text()
    if not send_immediately and not schedule_time:
        raise ModelRetry("Must provide either schedule_time or send_immediately=True")

    # Validate schedule_time if not sending immediately
    schedule_datetime: datetime.datetime | None = None
    if not send_immediately and schedule_time:
        try:
            schedule_datetime = datetime.datetime.fromisoformat(schedule_time)
        except ValueError as e:
            raise ModelRetry(
                f"Invalid schedule_time format. Use ISO 8601, e.g. '2025-06-04T15:00:00+08:00'. Error: {e}"
            )
        if schedule_datetime < datetime.datetime.now(datetime.UTC):
            raise ModelRetry("schedule_time must be in the future.")

    # Validate message content
    has_text = text is not None and text.strip()
    has_media = media_type is not None or media_url is not None

    if has_text and has_media:
        raise ModelRetry(
            "Cannot provide both text and media. Use caption for media description."
        )
    if not has_text and not has_media:
        raise ModelRetry("Must provide either text or media (media_type + media_url).")
    if has_media and not media_type:
        raise ModelRetry("media_type is required when providing media_url.")
    if has_media and not media_url:
        raise ModelRetry("media_url is required when providing media_type.")

    chat_id = ctx.deps.chat_id

    if send_immediately:
        # Send immediately without scheduling
        try:
            if has_text:
                assert text is not None
                await ctx.deps.client.send_message(chat_id=chat_id, text=text)
                return SendResult(success=True, message="Message sent.").text()
            else:
                # Send media immediately
                assert media_type is not None
                assert media_url is not None
                caption = caption if caption else ""
                match media_type:
                    case "photo":
                        await ctx.deps.client.send_photo(
                            chat_id=chat_id,
                            photo=media_url,
                            caption=caption,
                        )
                    case "video":
                        await ctx.deps.client.send_video(
                            chat_id=chat_id,
                            video=media_url,
                            caption=caption,
                        )
                    case "audio":
                        await ctx.deps.client.send_audio(
                            chat_id=chat_id,
                            audio=media_url,
                            caption=caption,
                        )
                    case "document":
                        await ctx.deps.client.send_document(
                            chat_id=chat_id,
                            document=media_url,
                            caption=caption,
                        )
                return SendResult(success=True, message=f"{media_type} sent.").text()
        except Exception as e:
            logger.error(f"Immediate send failed: {e.__class__.__name__}: {e}")
            return SendResult(success=False, message=f"Failed to send: {e}").text()
    else:
        # Schedule for later delivery
        # At this point schedule_datetime must be set (validated above)
        assert schedule_datetime is not None

        if has_text:
            # Schedule text message using module-level function
            assert text is not None
            text_content = text
            job_key = (
                f"agent_schedule_msg:{chat_id}:{ctx.deps.user_id}"
                f":{schedule_datetime.timestamp()}"
                f":{md5(text_content.encode()).hexdigest()}"
            )

            common.jobqueue.add_onetime_job(
                job_key,
                run_date=schedule_datetime,
                func=_scheduled_text_job,
                args=[chat_id, text_content],
            )
        else:
            # Schedule media message using module-level function
            assert media_type is not None
            assert media_url is not None
            _caption = caption if caption else ""
            job_key = (
                f"agent_schedule_media:{chat_id}:{ctx.deps.user_id}"
                f":{schedule_datetime.timestamp()}"
                f":{md5(media_url.encode()).hexdigest()}"
            )

            common.jobqueue.add_onetime_job(
                job_key,
                run_date=schedule_datetime,
                func=_scheduled_media_job,
                args=[chat_id, media_type, media_url, _caption],
            )

        return SendResult(
            success=True, message=f"Scheduled for {schedule_datetime.isoformat()}"
        ).text()


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

    # Use module-level function for persistence
    common.jobqueue.add_onetime_job(
        job_key,
        run_date=schedule_datetime,
        func=_scheduled_poll_job,
        args=[chat_id, question, options, is_anonymous, allows_multiple_answers],
    )


async def send_sticker(
    ctx: RunContext[datatype.ContextDeps],
    query: str,
) -> str:
    """Search for a semantically matching sticker and send it.

    Args:
        query: Natural language description of the desired sticker, e.g. "happy excited",
               "sad crying", "thumbs up approval".

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
    # Mark as already called this turn so prepare_periodic_sticker suppresses
    # the "MUST call" hint for any further steps within the same agent run.
    ctx.deps.tools_called_this_turn.add("send_sticker")
    return SendResult(success=True).text()


async def send_reaction(
    ctx: RunContext[datatype.ContextDeps],
    emoji: str,
    target_message_id: int | None = None,
) -> str:
    """Send a reaction (emoji) to a message.

    Args:
        emoji: The emoji to react with, e.g. "🥰", "❤️", "😡".
        target_message_id: Optional message ID to react to. If not provided,
            reacts to the current user's message.

    Returns:
        A SendResult indicating success or failure.
    """
    if ctx.deps.message is None:
        return SendResult(
            success=False, message="Message context is unavailable."
        ).text()

    # Use provided target message ID or default to current message
    message_id = (
        target_message_id if target_message_id is not None else ctx.deps.message.id
    )

    try:
        await ctx.deps.client.send_reaction(
            chat_id=ctx.deps.chat_id,
            message_id=message_id,
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
    # Mark as already called this turn so prepare_periodic_reaction suppresses
    # the "MUST call" hint for any further steps within the same agent run.
    ctx.deps.tools_called_this_turn.add("send_reaction")
    return SendResult(success=True).text()


__all__ = ["schedule_message", "send_poll", "send_reaction", "send_sticker"]
