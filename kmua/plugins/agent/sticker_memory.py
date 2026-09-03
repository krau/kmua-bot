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
from .whitelist import is_chat_allowed

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
    if _desc_spec:
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


def sample_rate_for(chat_count: int) -> float:
    """入库采样率: 库存低于 warmup 目标时线性放大到 1.0, 加快冷启动填充."""
    base = app_config.agent_sticker_memory_sample_rate
    target = app_config.agent_sticker_warmup_count
    if not target or target <= 0 or chat_count >= target:
        return base
    return base + (1.0 - base) * (1.0 - chat_count / target)


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


async def _is_admin_actor(
    client: PyrogramClient, message: pyrogram.types.Message
) -> bool:
    """Whether the message author is an administrator of the chat.

    Shared guard for the sticker admin commands.
    """
    user = message.from_user
    if not user or not user.id:
        return False
    chat = message.chat
    if not chat or not chat.id:
        return False
    if not is_chat_allowed(chat.id):
        return False
    try:
        member = await common.get_chat_member(client, chat.id, user.id)
    except Exception:
        return False
    return member.status in (
        pyrogram.enums.ChatMemberStatus.ADMINISTRATOR,
        pyrogram.enums.ChatMemberStatus.OWNER,
    )


@PyrogramClient.on_message(filters.command("addsticker") & filters.group, group=11)
async def add_sticker_command(
    client: PyrogramClient, message: pyrogram.types.Message
) -> None:
    """Let a group administrator add a sticker to this chat's memory.

    Reply to a sticker message with /addsticker; the sticker goes through
    the same pipeline as automatic sampling (download, description,
    embedding, store).
    """
    if not app_config.agent_sticker_memory:
        return
    if not await _is_admin_actor(client, message):
        return
    user = message.from_user
    if not user or not user.id:
        return
    chat = message.chat
    if not chat or not chat.id:
        return
    reply = message.reply_to_message
    if reply is None or reply.sticker is None:
        await message.reply_text("请回复一条贴纸消息")
        return
    sticker = reply.sticker
    chat_id = chat.id
    common.spawn(
        _process_sticker(client, sticker, chat_id),
        name=f"sticker-memory-{chat_id}",
    )
    logger.info(
        f"Sticker {sticker.file_unique_id} added to chat {chat_id} by {user.id}"
    )
    await message.reply_text("这个贴纸我记下啦, 之后可能会用它")


@PyrogramClient.on_message(filters.command("delsticker") & filters.group, group=11)
async def del_sticker_command(
    client: PyrogramClient, message: pyrogram.types.Message
) -> None:
    """Let a group administrator remove a sticker from this chat's memory.

    Reply to a sticker message with /delsticker; the sticker is dropped from
    the chat's sticker store (automatic eviction still manages the rest).
    """
    if not app_config.agent_sticker_memory:
        return
    if not await _is_admin_actor(client, message):
        return
    user = message.from_user
    if not user or not user.id:
        return
    chat = message.chat
    if not chat or not chat.id:
        return
    reply = message.reply_to_message
    if reply is None or reply.sticker is None:
        await message.reply_text("请回复一条贴纸消息")
        return
    deleted = await sticker_vec.delete(reply.sticker.file_unique_id, chat.id)
    if deleted:
        logger.info(
            f"Sticker {reply.sticker.file_unique_id} removed from "
            f"chat {chat.id} by {user.id}"
        )
        await message.reply_text("以后不会发这个贴纸啦 (只要别人也不发...")
    else:
        await message.reply_text("这个贴纸本就不在库中呢")


@PyrogramClient.on_message(filters.command("clearsticker") & filters.group, group=11)
async def clear_sticker_command(
    client: PyrogramClient, message: pyrogram.types.Message
) -> None:
    """Let a group administrator wipe this chat's entire sticker memory."""
    if not app_config.agent_sticker_memory:
        return
    if not await _is_admin_actor(client, message):
        return
    user = message.from_user
    if not user or not user.id:
        return
    chat = message.chat
    if not chat or not chat.id:
        return
    removed = await sticker_vec.clear(chat.id)
    if removed:
        logger.info(
            f"Sticker memory cleared for chat {chat.id} by {user.id}: {removed} stickers"
        )
        await message.reply_text(f"已清空本群的贴纸记忆 ({removed} 张贴纸)")
    else:
        await message.reply_text("本群贴纸库本来就是空的呢")


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
    if not is_chat_allowed(chat.id):
        return
    sticker = message.sticker
    if sticker is None:
        return
    chat_config = await database.get_chat_config(chat.id)
    if not chat_config.ai_reply:
        return
    if not chat_config.sticker_memory_enabled:
        return
    count = await sticker_vec.count(chat.id)
    if not common.random_chance(sample_rate_for(count)):
        return
    common.spawn(
        _process_sticker(client, sticker, chat.id),
        name=f"sticker-memory-{chat.id}",
    )
