import asyncio
from io import BytesIO

import pyrogram
import pyrogram.types
from pydantic_ai import Agent, BinaryContent, Embedder
from pydantic_ai.embeddings import EmbeddingSettings
from pyrogram import filters
from pyrogram.client import Client as PyrogramClient

from kmua import common, database
from kmua.config import app_config
from kmua.logger import logger

from . import provider, sticker_vec

embedder: Embedder | None = None
_description_agent: Agent[None, str] | None = None

if app_config.agent_sticker_memory:
    embedder = Embedder(
        provider.make_embed_model(app_config.agent_sticker_embed_model),
        settings=EmbeddingSettings(
            dimensions=app_config.agent_sticker_embed_dimensions
        ),
    )

    _desc_spec = app_config.agent_sticker_description_model or app_config.agent_model
    _description_agent = Agent(
        model=provider.make_chat_model(_desc_spec),
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


async def _get_description(image_bytes: bytes, mime_type: str) -> str | None:
    if _description_agent is None:
        return None
    try:
        if mime_type == "video/webm":
            frame = await common.webm_first_frame(image_bytes)
            if frame is None:
                return None
            content_part: BinaryContent = BinaryContent(
                data=frame,
                media_type="image/webp",  # type: ignore
            )
        else:
            content_part = BinaryContent(data=image_bytes, media_type=mime_type)  # type: ignore

        # 使用超时控制防止模型调用阻塞事件循环（贴纸描述使用小模型超时）
        timeout = app_config.agent_small_model_timeout
        coro = _description_agent.run(
            [content_part, app_config.agent_sticker_description_prompt]
        )

        if timeout > 0:
            try:
                result = await asyncio.wait_for(coro, timeout=timeout)
            except TimeoutError:
                logger.warning(f"sticker description timed out after {timeout}s")
                return None
        else:
            result = await coro

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

    if sticker.is_video and common.FFMPEG is None:
        return

    try:
        # 使用超时控制防止下载大文件阻塞事件循环
        timeout = app_config.agent_download_timeout
        if timeout > 0:
            raw = await asyncio.wait_for(
                client.download_media(file_id, in_memory=True), timeout=timeout
            )
        else:
            raw = await client.download_media(file_id, in_memory=True)
        if not isinstance(raw, BytesIO):
            return
        image_bytes = raw.getvalue()
    except TimeoutError:
        logger.warning(f"sticker download timed out for {file_unique_id}")
        return
    except Exception as e:
        logger.error(f"sticker download error: {e.__class__.__name__}: {e}")
        return

    mime_type = "video/webm" if sticker.is_video else "image/webp"
    description = await _get_description(image_bytes, mime_type)
    if not description:
        logger.warning(f"sticker {file_unique_id}: no description generated, skipping")
        return

    embedding = await get_embedding(description)
    if not embedding:
        logger.warning(f"sticker {file_unique_id}: no embedding generated, skipping")
        return

    await sticker_vec.upsert(file_unique_id, file_id, chat_id, description, embedding)


_sticker_filter = filters.sticker & (filters.group) & ~filters.bot


@PyrogramClient.on_message(_sticker_filter, group=11)
async def on_sticker(client: PyrogramClient, message: pyrogram.types.Message) -> None:
    if not app_config.agent:
        return
    if not app_config.agent_sticker_memory:
        return
    if embedder is None or _description_agent is None:
        return
    chat = message.chat
    if not chat or not chat.id:
        return
    sticker = message.sticker
    if sticker is None:
        return
    if not common.random_chance(app_config.agent_sticker_memory_sample_rate):
        return
    if not (await database.get_chat_config(chat.id)).ai_reply:
        return
    asyncio.create_task(_process_sticker(client, sticker, chat.id))
