import datetime
import mimetypes

import pyrogram
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pyrogram.client import Client

from kmua import database
from kmua.common.memory_store import memttlcache
from kmua.config import app_config
from kmua.logger import logger
from kmua.plugins.agent.output import TypingKeepAlive, reply_output
from kmua.plugins.agent.prompt import get_input_prompt
from kmua.plugins.agent.runner import get_chat_prompt_override

from .agent import struct_model
from .whitelist import is_chat_allowed


class CommentResult(BaseModel):
    comment: str = Field(description="评论内容")
    poll_question: str | None = Field(default=None, description="投票问题")
    poll_options: list[str] | None = Field(
        default=None, description="投票选项", min_length=2, max_length=10
    )
    poll_is_anonymous: bool = Field(default=True, description="投票是否匿名")


comment_agent = Agent(model=struct_model, output_type=CommentResult, retries=5)


async def _is_first_media_in_group(message: pyrogram.types.Message) -> bool:
    """Return True only for the first message of a media group.

    For non-album messages (no media_group_id), always returns True.
    """
    media_group_id = message.media_group_id
    if not media_group_id:
        return True

    chat = message.chat
    if chat is None or chat.id is None:
        return True

    if not (message.caption or message.text):
        return False

    # 同一个 media_group 只处理一次
    key = f"channel_comment_media_group:{chat.id}:{media_group_id}"
    if await memttlcache.get(key, False):
        return False

    await memttlcache.set(key, True, ttl=60)
    return True


def _message_has_unsupported_media(message: pyrogram.types.Message) -> bool:
    """Return True if the message contains media that get_input_prompt cannot process.

    This mirrors the media handling logic in get_input_prompt so that comments
    are skipped when the model would only see a caption without the actual media.

    Supported media breakdown (matching get_input_prompt exactly):
    - POLL: always converted to text (supported regardless of settings).
    - WEB_PAGE: URL text is always visible (supported).
    - All other media types require app_config.agent_multimodal == True.
      - PHOTO: supported when "photo" is in agent_multimodal_inputs.
      - LIVE_PHOTO: NOT handled in get_input_prompt (unsupported).
      - VIDEO: supported when "video" in inputs, file_size <= 20 MiB.
      - AUDIO: supported when "audio" in inputs, file_size <= 10 MiB.
      - VOICE: supported when "audio" in inputs, file_size <= 10 MiB.
      - DOCUMENT:
        - text/* mime types are read as plain text (supported).
        - image/* requires "photo" in inputs, file_size <= 10 MiB.
        - Specific mime types listed in agent_multimodal_inputs,
          file_size <= 10 MiB.
        - Everything else is unsupported.
      - STICKER:
        - Animated stickers are unsupported.
        - Video/static stickers require "photo" in inputs.
    """
    if not message.media:
        return False

    # POLL is always converted to text; WEB_PAGE URL text is always visible.
    if message.media in (
        pyrogram.enums.MessageMediaType.POLL,
        pyrogram.enums.MessageMediaType.WEB_PAGE,
    ):
        return False

    # All remaining media types require agent_multimodal to be processed.
    if not app_config.agent_multimodal:
        return True

    match message.media:
        case pyrogram.enums.MessageMediaType.PHOTO:
            photo = message.photo
            return not (
                photo and photo.file_id and "photo" in app_config.agent_multimodal_inputs
            )

        case pyrogram.enums.MessageMediaType.LIVE_PHOTO:
            # get_input_prompt has no handler for LIVE_PHOTO.
            return True

        case pyrogram.enums.MessageMediaType.VIDEO:
            video = message.video
            return not (
                video
                and video.file_id
                and video.mime_type
                and video.file_size
                and video.file_size <= 20 * 1024 * 1024
                and "video" in app_config.agent_multimodal_inputs
            )

        case pyrogram.enums.MessageMediaType.AUDIO:
            audio = message.audio
            return not (
                audio
                and audio.file_id
                and audio.mime_type
                and audio.file_size
                and audio.file_size <= 10 * 1024 * 1024
                and "audio" in app_config.agent_multimodal_inputs
            )

        case pyrogram.enums.MessageMediaType.VOICE:
            voice = message.voice
            return not (
                voice
                and voice.file_id
                and voice.mime_type
                and voice.file_size
                and voice.file_size <= 10 * 1024 * 1024
                and "audio" in app_config.agent_multimodal_inputs
            )

        case pyrogram.enums.MessageMediaType.DOCUMENT:
            document = message.document
            if not document or not document.file_id:
                return True
            if not document.file_size or document.file_size > 10 * 1024 * 1024:
                return True
            mime_type = document.mime_type
            if not mime_type:
                mime_type, _ = mimetypes.guess_type(document.file_name or "")
                mime_type = mime_type or "application/octet-stream"
            mime_type = mime_type.split(";")[0]
            # Plain text documents are readable as text.
            if mime_type.startswith("text/"):
                return False
            if mime_type.startswith("image/") and "photo" in app_config.agent_multimodal_inputs:
                return False
            if mime_type in app_config.agent_multimodal_inputs:
                return False
            return True

        case pyrogram.enums.MessageMediaType.STICKER:
            sticker = message.sticker
            if not sticker or not sticker.file_id:
                return True
            if sticker.is_animated:
                return True
            return "photo" not in app_config.agent_multimodal_inputs

        case _:
            # ANIMATION, VIDEO_NOTE, LOCATION, VENUE, CONTACT, DICE, GAME,
            # GIVEAWAY, GIVEAWAY_WINNERS, STORY, INVOICE, PAID_MEDIA,
            # CHECKLIST, UNSUPPORTED — none are handled by get_input_prompt.
            return True


async def channel_comment_filter_func(_, __, message: pyrogram.types.Message):
    chat = message.chat
    if chat is None:
        return False
    if chat.type not in (
        pyrogram.enums.ChatType.SUPERGROUP,
        pyrogram.enums.ChatType.GROUP,
    ):
        return False
    if not message.automatic_forward:
        return False
    if _message_has_unsupported_media(message):
        return False
    if comment_agent is None:
        return False
    if not app_config.agent:
        return False
    if not chat.id or not is_chat_allowed(chat.id):
        return False
    chat_config = await database.get_chat_config(chat)
    if not chat_config.ai_comment:
        return False
    return True


channel_comment_filter = pyrogram.filters.create(channel_comment_filter_func)


@Client.on_message(channel_comment_filter, group=2)  # 2 to after unpin
async def comment_channel_message(client: Client, message: pyrogram.types.Message):
    if not app_config.agent:
        return
    chat = message.chat
    if chat is None or chat.id is None:
        return
    if not is_chat_allowed(chat.id):
        return
    channel = message.sender_chat
    if channel is None or channel.id is None:
        return

    # 对相册消息（media group）只在第一条媒体上触发评论
    if not await _is_first_media_in_group(message):
        return
    # 构建 instructions：base prompt → per-chat override → ctx 信息
    instructions = (
        app_config.agent_group_prompt
        if app_config.agent_group_prompt
        else app_config.agent_prompt
    )
    prompt_override = await get_chat_prompt_override(chat.id)
    if prompt_override:
        instructions = prompt_override
    ctx_parts = [
        "任务类型: 频道评论",
        f"频道名称: {channel.title}",
        f"频道简介: {channel.bio or channel.description}",
        f"当前时间: {datetime.datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')}",
        f"任务描述: {app_config.agent_channel_comment_prompt}",
    ]
    instructions += "\n\n" + "\n".join(ctx_parts)

    prompts, _ = await get_input_prompt(client, message, ctx=None)
    if not prompts:
        return
    logger.debug(f"Channel comment post: {message.caption or message.text}")
    try:
        async with TypingKeepAlive(client, message):
            result = await comment_agent.run(
                model=struct_model,
                instructions=instructions,
                user_prompt=prompts,
            )
            output = result.output
            if output.comment:
                await reply_output(client, message, output.comment)
            if (
                output.poll_question
                and output.poll_options
                and len(output.poll_options) >= 2
            ):
                await client.send_poll(
                    chat_id=chat.id,
                    question=output.poll_question,
                    options=output.poll_options,
                    is_anonymous=output.poll_is_anonymous,
                    reply_parameters=pyrogram.types.ReplyParameters(
                        message_id=message.id
                    ),
                )
    except Exception as e:
        logger.error(f"Channel comment error: {e.__class__.__name__} - {e}")
