import asyncio
import random
import shutil

import pyrogram

from kmua.logger import logger

FFMPEG = shutil.which("ffmpeg")


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
    """Extract first frame from a WEBM video as WebP using ffmpeg."""
    if FFMPEG is None:
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
        stdout, _ = await proc.communicate(input=webm_bytes)
        if proc.returncode != 0 or not stdout:
            logger.error(f"ffmpeg frame extraction failed (rc={proc.returncode})")
            return None
        return stdout
    except Exception as e:
        logger.error(f"ffmpeg error: {e.__class__.__name__}: {e}")
        return None
