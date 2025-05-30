import time

import pyrogram
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.tools import Tool
from pyrogram import filters

from kmua import common
from kmua.config import app_config
from kmua.logger import logger

from . import myfilter, utils
from .simple_reply import word_reply

agent = None
if app_config.agent:
    model = OpenAIModel(
        model_name=app_config.agent_model,
        provider=OpenAIProvider(
            base_url=app_config.agent_provider_url,
            api_key=app_config.agent_api_key,
        ),
    )
    agent = Agent(model=model, system_prompt=app_config.agent_prompt)


def _history_key(user_id: int) -> str:
    return f"message_history_with_agent:{user_id}"


def _waiting_key(user_id: int) -> str:
    return f"agent_waiting:{user_id}"


@pyrogram.Client.on_message(
    myfilter.base_filter
    & (myfilter.reply_me_filter | filters.private | myfilter.mention_me_filter),
    group=0,
)
async def wake_agent(client: pyrogram.Client, message: pyrogram.types.Message):
    user = message.sender_chat or message.from_user
    if not app_config.agent or await common.memstore.get(_waiting_key(user.id)):
        return await word_reply(client, message)
    await message.reply_chat_action(pyrogram.enums.ChatAction.TYPING)
    await common.memstore.set(_waiting_key(user.id), True)
    try:
        history = await common.memttlcache.get(_history_key(user.id), [])
        async with agent.run_stream(
            message.text,
            message_history=history,
        ) as result:
            replied = None
            buffer = ""
            last_edit = time.monotonic()
            async for msg in result.stream_text():
                buffer = msg
                if time.monotonic() - last_edit <= 2.33 and replied:
                    continue
                if not replied:
                    replied = await message.reply_text(buffer)
                else:
                    replied = await replied.edit_text(buffer)
                last_edit = time.monotonic()
            if not replied:
                replied = await message.reply_text(buffer)
            else:
                replied = await replied.edit_text(buffer)
        summary = await utils.summarize_history(agent, result.all_messages())
        await common.memttlcache.set(_history_key(user.id), summary, ttl=86400 * 2)
        logger.debug(summary)
    finally:
        await common.memstore.delete(_waiting_key(user.id))
