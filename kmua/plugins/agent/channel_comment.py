import datetime

import pyrogram
from pyrogram.client import Client

from kmua import database
from kmua.common.memory_store import memttlcache
from kmua.config import app_config
from kmua.logger import logger
from kmua.plugins.agent import datatype, utils

from .agent import agent, model, multimodal_model


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
    if agent is None:
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
    ctx = {
        "task_type": "channel_comment",
        "task_desc": "评论这条频道的帖子",
        "channel_name": channel.title,
        "channel_bio": channel.bio or channel.description,
        "current_time": datetime.datetime.now().strftime("%Y年%m月%d日 %H:%M:%S"),
    }
    prompts, needs_multimodal = await utils.get_input_prompt(client, message, ctx=ctx)
    if not prompts:
        return
    logger.debug(f"Channel comment post: {message.caption or message.text}")
    use_model = multimodal_model if needs_multimodal else model
    resp = await agent.run(
        model=use_model,
        toolsets=None,
        user_prompt=prompts,
        deps=datatype.ContextDeps(
            client=client,
            user_id=channel.id,
            chat_id=chat.id,
            message=message,
        ),
    )
    if not resp or not resp.output:
        logger.debug("No response from agent for channel comment.")
        return
    logger.debug(f"Channel comment response: {resp.output}")
    await message.reply_text(
        text=resp.output,
        reply_to_message_id=message.id,
    )
