import datetime

import pyrogram
from pyrogram.client import Client

from kmua import database
from kmua.config import app_config
from kmua.logger import logger
from kmua.plugins.agent import datatype

from .agent import agent, get_input_prompt


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
    ctx = {
        "task_type": "channel_comment",
        "task_desc": "评论这条频道的帖子",
        "channel_name": channel.title,
        "channel_bio": channel.bio or "",
        "current_time": datetime.datetime.now().strftime("%Y年%m月%d日 %H:%M:%S"),
    }
    prompts = await get_input_prompt(client, message, ctx)
    logger.debug(f"Channel comment prompts: {prompts}")
    if not prompts:
        return
    resp = await agent.run(
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
