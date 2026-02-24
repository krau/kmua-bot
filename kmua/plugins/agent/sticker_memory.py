import asyncio
import shutil
from io import BytesIO

import pyrogram
import pyrogram.types
from pydantic_ai import Agent, BinaryContent, Embedder
from pydantic_ai.embeddings import EmbeddingSettings
from pydantic_ai.embeddings.openai import OpenAIEmbeddingModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pyrogram import filters
from pyrogram.client import Client as PyrogramClient

from kmua.config import app_config
from kmua.logger import logger

from . import sticker_vec

embedder: Embedder | None = None
_description_agent: Agent[None, str] | None = None

_FFMPEG = shutil.which("ffmpeg")


if app_config.agent_sticker_memory:
    _embed_api_key = app_config.agent_sticker_embed_api_key or app_config.agent_api_key
    _embed_base_url = (
        app_config.agent_sticker_embed_provider_url or app_config.agent_provider_url
    )
    embedder = Embedder(
        OpenAIEmbeddingModel(
            app_config.agent_sticker_embed_model,
            provider=OpenAIProvider(
                base_url=_embed_base_url,
                api_key=_embed_api_key,
            ),
        ),
        settings=EmbeddingSettings(
            dimensions=app_config.agent_sticker_embed_dimensions
        ),
    )

    _desc_model_name = (
        app_config.agent_sticker_description_model or app_config.agent_model
    )
    _desc_api_key = app_config.agent_sticker_embed_api_key or app_config.agent_api_key
    _desc_base_url = (
        app_config.agent_sticker_embed_provider_url or app_config.agent_provider_url
    )
    _description_agent = Agent(
        model=OpenAIChatModel(
            model_name=_desc_model_name,
            provider=OpenAIProvider(
                base_url=_desc_base_url,
                api_key=_desc_api_key,
            ),
        ),
        output_type=str,
        retries=2,
    )


async def get_embedding(text: str) -> list[float] | None:
    if embedder is None:
        return None
    try:
        result = await embedder.embed_query(text)
        return list(result.embeddings[0])
    except Exception as e:
        logger.error(f"sticker embed error: {e.__class__.__name__}: {e}")
        return None


async def _webm_first_frame(webm_bytes: bytes) -> bytes | None:
    """Extract first frame from a WEBM video as WebP using ffmpeg."""
    if _FFMPEG is None:
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            _FFMPEG,
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


async def _get_description(image_bytes: bytes, mime_type: str) -> str | None:
    if _description_agent is None:
        return None
    try:
        if mime_type == "video/webm":
            frame = await _webm_first_frame(image_bytes)
            if frame is None:
                return None
            content_part: BinaryContent = BinaryContent(
                data=frame, media_type="image/webp"
            )
        else:
            content_part = BinaryContent(data=image_bytes, media_type=mime_type)
        result = await _description_agent.run(
            [content_part, app_config.agent_sticker_description_prompt]
        )
        return result.output
    except Exception as e:
        logger.error(f"sticker description error: {e.__class__.__name__}: {e}")
        return None


async def _process_sticker(
    client: PyrogramClient,
    sticker: pyrogram.types.Sticker,
    chat_id: int,
) -> None:
    file_unique_id = sticker.file_unique_id
    file_id = sticker.file_id

    if await sticker_vec.exists(file_unique_id, chat_id):
        await sticker_vec.touch(file_unique_id, chat_id)
        return

    if sticker.is_animated:
        return

    if sticker.is_video and _FFMPEG is None:
        return

    try:
        raw = await client.download_media(file_id, in_memory=True)  # type: ignore[assignment]
        if not isinstance(raw, BytesIO):
            return
        image_bytes = raw.getvalue()
    except Exception as e:
        logger.error(f"sticker download error: {e.__class__.__name__}: {e}")
        return

    mime_type = "video/webm" if sticker.is_video else "image/webp"
    description = await _get_description(image_bytes, mime_type)
    if not description:
        logger.debug(f"sticker {file_unique_id}: no description generated, skipping")
        return

    embedding = await get_embedding(description)
    if not embedding:
        logger.debug(f"sticker {file_unique_id}: no embedding generated, skipping")
        return

    await sticker_vec.upsert(file_unique_id, file_id, chat_id, description, embedding)
    logger.debug(f"sticker {file_unique_id} stored for chat {chat_id}: {description!r}")


_sticker_filter = filters.sticker & (filters.group) & ~filters.bot


@PyrogramClient.on_message(_sticker_filter, group=11)
async def on_sticker(client: PyrogramClient, message: pyrogram.types.Message) -> None:
    if not app_config.agent_sticker_memory:
        return
    if embedder is None or _description_agent is None:
        return
    sticker = message.sticker
    if sticker is None:
        return
    chat = message.chat
    if chat is None or chat.id is None:
        return

    asyncio.create_task(_process_sticker(client, sticker, chat.id))
