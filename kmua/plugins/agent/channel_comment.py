import datetime

import pyrogram
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pyrogram.client import Client

from kmua import database
from kmua.common.memory_store import memttlcache
from kmua.config import app_config
from kmua.logger import logger
from kmua.plugins.agent import provider
from kmua.plugins.agent.output import TypingKeepAlive, reply_output
from kmua.plugins.agent.prompt import get_input_prompt
from kmua.plugins.agent.runner import get_chat_model_override, get_chat_prompt_override

from .agent import model, multimodal_model


class CommentResult(BaseModel):
    comment: str = Field(description="评论内容")
    poll_question: str | None = Field(default=None, description="投票问题")
    poll_options: list[str] | None = Field(
        default=None, description="投票选项", le=10, ge=2
    )
    poll_is_anonymous: bool = Field(default=True, description="投票是否匿名")


comment_agent = Agent(model=model, output_type=CommentResult, retries=5)


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
    if comment_agent is None:
        return False
    if not app_config.agent:
        return False
    chat_config = await database.get_chat_config(chat)
    if not chat_config.ai_comment:
        return False
    return True


channel_comment_filter = pyrogram.filters.create(channel_comment_filter_func)


@Client.on_message(channel_comment_filter, group=2)  # 2 to after unpin
async def comment_channel_message(client: Client, message: pyrogram.types.Message):
    chat = message.chat
    if chat is None or chat.id is None:
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

    prompts, needs_multimodal = await get_input_prompt(client, message, ctx=None)
    if not prompts:
        return
    logger.debug(f"Channel comment post: {message.caption or message.text}")
    if needs_multimodal:
        override_name = await get_chat_model_override(chat.id, "multimodal")
    else:
        override_name = await get_chat_model_override(chat.id, "main")
    if override_name:
        use_model = provider.make_chat_model(override_name)
    else:
        use_model = multimodal_model if needs_multimodal else model
    try:
        async with TypingKeepAlive(client, message):
            result = await comment_agent.run(
                model=use_model,
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
