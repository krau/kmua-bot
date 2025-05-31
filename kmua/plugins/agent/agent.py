import pyrogram
from pydantic_ai import Agent
from pydantic_ai.common_tools.duckduckgo import duckduckgo_search_tool
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider
from pyrogram import filters

from kmua import common, database, i18n
from kmua.config import app_config
from kmua.logger import logger
from kmua.plugins.manyacg.manyacg import ARTWORK_ALL_REGEX

from . import datatype, myfilter, tools, utils
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
    agent = Agent(
        model=model,
        system_prompt=app_config.agent_prompt,
        tools=[
            tools.get_history_messages,
            tools.get_current_time,
            tools.get_ip_info,
            tools.get_user_info,
            tools.get_chat_info,
            tools.get_and_send_a_anime_photo,
            duckduckgo_search_tool(),
        ],
        deps_type=datatype.ContextDeps,
    )

    @pyrogram.Client.on_message(pyrogram.filters.command("forget"), group=0)
    async def forget_history(client: pyrogram.Client, message: pyrogram.types.Message):
        user = message.sender_chat or message.from_user
        user_config = await database.get_user_config(user)
        if await common.memstore.get(_waiting_key(user.id)):
            await message.reply_text(
                i18n.t("bot.msg.agent.waiting", locale=user_config.lang)
            )
            return
        chat_id = message.chat.id if message.chat else user.id
        await common.memttlcache.delete(_history_key(chat_id, user.id))
        await message.reply_text(
            i18n.t("bot.msg.agent.forgot", locale=user_config.lang)
        )


def _history_key(chat_id: int, user_id: int) -> str:
    return f"message_history_with_agent:{chat_id}:{user_id}"


def _waiting_key(user_id: int) -> str:
    return f"agent_waiting:{user_id}"


@pyrogram.Client.on_message(
    ~pyrogram.filters.regex("|".join([r.pattern for r in ARTWORK_ALL_REGEX]))
    & myfilter.base_filter
    & (myfilter.reply_me_filter | filters.private | myfilter.mention_me_filter),
    group=0,
)
async def wake_agent(client: pyrogram.Client, message: pyrogram.types.Message):
    user = message.sender_chat or message.from_user
    if not user:
        return await word_reply(client, message)
    if not app_config.agent or await common.memstore.get(_waiting_key(user.id)):
        return await word_reply(client, message)
    chat = message.chat
    if not chat:
        return await word_reply(client, message)
    if chat.type == pyrogram.enums.ChatType.SUPERGROUP:
        chat_config = await database.get_chat_config(chat)
        if not chat_config.ai_reply:
            return await word_reply(client, message)

    await message.reply_chat_action(pyrogram.enums.ChatAction.TYPING)
    await common.memstore.set(_waiting_key(user.id), True)
    try:
        chat_id = message.chat.id
        history = await common.memttlcache.get(_history_key(chat_id, user.id), [])
        user_prompt = message.text or message.caption or ""
        if reply_to := message.reply_to_message:
            user_prompt += f"""
[REPLY TO MESSAGE](MessageID: {reply_to.id}):
{reply_to.text or reply_to.caption or "[NO TEXT]"}
"""
        context_info = f"""
[CONTEXT INFO]:
MessageID: {message.id}
[USER MESSAGE]:
"""
        user_prompt = context_info + user_prompt
        logger.debug(f"User {user.id} prompt: {user_prompt}")
        result = await agent.run(
            user_prompt,
            message_history=history,
            deps=datatype.ContextDeps(
                user_id=user.id,
                chat_id=chat_id,
                message=message,
                client=client,
            ),
        )
        await message.reply_text(
            result.output,
            parse_mode=pyrogram.enums.ParseMode.MARKDOWN,
        )
        summary = await utils.summarize_history(agent, result.all_messages())
        await common.memttlcache.set(
            _history_key(chat_id, user.id), summary, ttl=86400 * 2
        )
    finally:
        await common.memstore.delete(_waiting_key(user.id))
