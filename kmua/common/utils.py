import asyncio
import random
import shutil

import pyrogram
from pyrogram.types import Message

from kmua.logger import logger

FFMPEG = shutil.which("ffmpeg")

# 最大 WEBM 文件大小 (10MB) - 超过此大小将跳过处理以避免阻塞
MAX_WEBM_SIZE = 10 * 1024 * 1024
# WEBM 处理超时 (秒)
WEBM_PROCESS_TIMEOUT = 10

# Strong references to background tasks so they are not garbage-collected
# mid-flight (asyncio only keeps weak references to tasks).
_background_tasks: set[asyncio.Task] = set()


def _on_task_done(task: asyncio.Task) -> None:
    _background_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.opt(exception=exc).error(
            f"Background task {task.get_name()!r} raised an unhandled exception: "
            f"{exc.__class__.__name__} - {exc}"
        )


def spawn(coro, *, name: str | None = None) -> asyncio.Task:
    """Schedule a coroutine as a background task safely.

    Unlike a bare ``asyncio.create_task``:
    - keeps a strong reference until the task finishes (prevents the task from
      being silently garbage-collected before completion), and
    - logs any unhandled exception instead of swallowing it.
    """
    task = asyncio.create_task(coro, name=name)
    _background_tasks.add(task)
    task.add_done_callback(_on_task_done)
    return task


def get_msg_link(message: pyrogram.types.Message) -> str:
    try:
        chat = message.chat
        if chat is None:
            raise ValueError("Chat is None")
        link = f"https://t.me/c/{str(chat.id).removeprefix('-100')}/{message.id}"
        return link
    except Exception:
        return ""


def parse_msg_link(link: str) -> tuple[int, int] | None:
    split_link = link.split("/")
    try:
        chat_id = int("-100" + split_link[-2])
        message_id = int(split_link[-1])
    except ValueError:
        return None
    return chat_id, message_id


def random_chance(probability: float) -> bool:
    """Returns True with a given probability."""
    # probability should be between 0 and 1
    if probability < 0:
        return False
    if probability > 1:
        return True
    return random.uniform(0, 1) < probability


async def webm_first_frame(webm_bytes: bytes) -> bytes | None:
    """Extract first frame from a WEBM video as WebP using ffmpeg.

    Args:
        webm_bytes: Raw WEBM file bytes

    Returns:
        WebP bytes of first frame, or None if failed
    """
    if FFMPEG is None:
        return None

    # 检查文件大小，避免处理过大文件
    if len(webm_bytes) > MAX_WEBM_SIZE:
        logger.debug(f"WEBM file too large ({len(webm_bytes)} bytes), skipping")
        return None

    try:
        proc = await asyncio.create_subprocess_exec(
            FFMPEG,
            "-i",
            "pipe:0",
            "-vframes",
            "1",
            "-f",
            "webp",
            "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

        # 使用 wait_for 添加超时控制
        try:
            stdout, _ = await asyncio.wait_for(
                proc.communicate(input=webm_bytes), timeout=WEBM_PROCESS_TIMEOUT
            )
        except TimeoutError:
            logger.warning(
                f"ffmpeg frame extraction timed out after {WEBM_PROCESS_TIMEOUT}s"
            )
            # 终止超时进程
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            return None

        if proc.returncode != 0 or not stdout:
            logger.error(f"ffmpeg frame extraction failed (rc={proc.returncode})")
            return None
        return stdout
    except Exception as e:
        logger.error(f"ffmpeg error: {e.__class__.__name__}: {e}")
        return None


def is_explicit_reply(message: Message) -> bool:
    """Check if a message is an explicit user reply (not auto-reply in forum topics).

    In Telegram forum groups, messages in a topic automatically have reply_to_message
    pointing to the topic creation message. This function distinguishes between:
    - True user reply: User explicitly replied to a specific message
    - Auto topic reply: Message is just in a topic (reply_to_message == topic creation msg)

    Args:
        message: The message to check

    Returns:
        True if this is an explicit user reply, False otherwise
    """
    if not message.reply_to_message:
        return False

    # Get reply information from the message
    # In Pyrogram, reply_to_message_id and reply_to_top_message_id are exposed directly
    reply_to_top_id = getattr(message, "reply_to_top_message_id", None)

    # In forum topics:
    # - Explicit reply: both reply_to_message_id and reply_to_top_id exist
    #   (reply_to_top_id points to the topic creation message)
    # - Auto-reply (no explicit reply): only reply_to_message_id exists, reply_to_top_id is None
    if reply_to_top_id is not None:
        # Has reply_to_top_id, this is an explicit reply in forum topic
        return True

    # reply_to_top_id is None, check if this is a forum topic message
    # topic_message is True when the message is in a forum topic
    is_topic = getattr(message, "topic_message", False)

    if is_topic:
        # In forum topic without reply_to_top_id, this is auto-reply
        return False

    # Not in forum topic, this is a regular reply in normal group
    return True


def get_reply_target(message: Message) -> Message | None:
    """Get the message that the user explicitly replied to.

    This function safely gets the reply target, handling forum topic groups where
    messages automatically reply to the topic creation message.

    Args:
        message: The message to check

    Returns:
        The replied-to message if it's an explicit reply, None otherwise
    """
    if not is_explicit_reply(message):
        return None
    return message.reply_to_message
