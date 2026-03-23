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

    # Check if this is a forum topic auto-reply
    # In forum topics, reply_to_message_id equals reply_to_top_message_id
    # when the message is automatically replying to the topic creation message
    reply_to_msg_id = getattr(message, "reply_to_message_id", None)
    reply_to_top_id = getattr(message, "reply_to_top_message_id", None)

    if reply_to_msg_id and reply_to_top_id and reply_to_msg_id == reply_to_top_id:
        return False

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
