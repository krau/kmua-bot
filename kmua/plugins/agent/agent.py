import asyncio

import pyrogram
from ddgs import DDGS
from powermem import AsyncMemory
from pydantic_ai import (
    Agent,
    DeferredToolRequests,
    ModelMessage,
    RunContext,
    Tool,
)
from pydantic_ai.common_tools.duckduckgo import DuckDuckGoSearchTool
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pyrogram import filters
from pyrogram.client import Client as PyrogramClient

from kmua import common, database, i18n
from kmua.config import app_config
from kmua.logger import logger
from kmua.services import manyacg

from . import datatype, myfilter, state, tools, utils
from .history import get_history_text, should_compress_by_tokens, summarize_history
from .prompt import build_ctx_info, get_input_prompt
from .runner import run_agent
from .simple_reply import word_reply

agent = None
model = None
small_model = None
multimodal_model = None
summary_agent = None
memory_agent = None
powermemory = None

if app_config.agent_powermem_config is not None:
    # for group memory, the key is f"group_{chat_id}"
    powermemory = AsyncMemory(app_config.agent_powermem_config)

    async def _init_powermem():
        assert powermemory is not None
        await powermemory.initialize()

    asyncio.create_task(_init_powermem())


async def history_processor(
    ctx: RunContext[datatype.ContextDeps], messages: list[ModelMessage]
) -> list[ModelMessage]:
    assert summary_agent is not None, "summary_agent is not initialized"
    assert memory_agent is not None, "memory_agent is not initialized"
    summary = await summarize_history(summary_agent, messages)
    await common.memttlcache.set(
        state.history_key(ctx.deps.chat_id, ctx.deps.user_id),
        summary,
        ttl=app_config.cachettl_agent_history,
    )
    should_update_memory = (
        should_compress_by_tokens(messages)
        if app_config.agent_context_window_tokens
        else len(messages) >= app_config.agent_messages_threshold
    )
    if should_update_memory:
        try:
            history_text = get_history_text(messages)
            await utils.update_user_memory(memory_agent, history_text, ctx.deps.user_id)
        except Exception as e:
            logger.exception(
                f"Error updating memory for user {ctx.deps.user_id}: {e.__class__.__name__} - {e}"
            )
    return summary


if app_config.agent:
    model = OpenAIChatModel(
        model_name=app_config.agent_model,
        provider=OpenAIProvider(
            base_url=app_config.agent_provider_url,
            api_key=app_config.agent_api_key,
        ),
    )
    multimodal_model = (
        model
        if not app_config.agent_model_multimodal
        else OpenAIChatModel(
            model_name=app_config.agent_model_multimodal,
            provider=OpenAIProvider(
                base_url=app_config.agent_provider_url,
                api_key=app_config.agent_api_key,
            ),
        )
    )
    small_model = (
        model
        if not app_config.agent_model_small
        else OpenAIChatModel(
            model_name=app_config.agent_model_small,
            provider=OpenAIProvider(
                base_url=app_config.agent_provider_url,
                api_key=app_config.agent_api_key,
            ),
        )
    )
    agent = Agent(
        model=model,
        instructions=app_config.agent_prompt,
        output_type=[str, DeferredToolRequests],
        tools=[
            Tool(tools.get_chat_info, prepare=tools.prepare_group_tools),
            Tool(tools.get_history_messages, prepare=tools.prepare_group_tools),
            Tool(
                DuckDuckGoSearchTool(DDGS(), max_results=3).__call__,
                name="duckduckgo_search",
                description="Searches DuckDuckGo for the given query and returns the results.",
                prepare=tools.prepare_configurable_tools,
            ),
            Tool(
                tools.search_messages,
                prepare=tools.prepare_message_search_tool,
            ),
            Tool(
                tools.send_chat_quote,
                prepare=tools.prepare_group_tools,
            ),
            Tool(
                tools.search_group_memory,
                prepare=tools.prepare_powermem_tool,
            ),
            Tool(
                tools.update_group_memory,
                prepare=tools.prepare_powermem_tool,
            ),
            Tool(
                tools.generate_image,
                prepare=tools.prepare_image_gen_tools,
            ),
            Tool(
                tools.edit_image,
                prepare=tools.prepare_image_edit_tools,
            ),
            Tool(
                tools.webfetch,
                prepare=tools.prepare_configurable_tools,
            ),
            Tool(
                tools.send_sticker,
                prepare=tools.prepare_sticker_tool,
            ),
            tools.ask_user,
            tools.send_anime_photo,
            tools.send_reaction,
            tools.send_media,
            tools.send_poll,
        ],
        deps_type=datatype.ContextDeps,
        history_processors=[history_processor],
        retries=5,
    )
    tools.set_agent(agent, model=model, multimodal_model=multimodal_model)
    summary_agent = Agent(model=model, instructions=app_config.agent_summary_prompt)
    memory_agent = Agent(
        model=model,
        output_type=datatype.UserMemoryResult,
        instructions=app_config.agent_memory_prompt,
    )

    @PyrogramClient.on_message(pyrogram.filters.command("forget"), group=0)
    async def forget_history(client: PyrogramClient, message: pyrogram.types.Message):
        user = message.sender_chat or message.from_user
        if not user or user.id is None:
            return
        user_config = await database.get_user_config(user.id)
        if await common.memstore.get(state.waiting_key(user.id)):
            await message.reply_text(
                i18n.t("bot.msg.agent.waiting", locale=user_config.lang)
            )
            return
        chat_id = message.chat.id if message.chat else user.id
        if not chat_id:
            return
        await common.memttlcache.delete(state.history_key(chat_id, user.id))
        await tools.clear_ask_state(chat_id, user.id)
        await message.reply_text(
            i18n.t("bot.msg.agent.forgot", locale=user_config.lang)
        )


_filter = (
    myfilter.base_filter
    & (myfilter.reply_me_filter | filters.private | myfilter.mention_me_filter)
    & myfilter.not_bottle_reply_filter
    & ~pyrogram.filters.regex("|".join([r.pattern for r in manyacg.ARTWORK_ALL_REGEX]))
)


@PyrogramClient.on_message(_filter, group=0)
async def wake_agent(client: PyrogramClient, message: pyrogram.types.Message):
    # some check
    if not agent:
        return await word_reply(client, message)
    user = message.sender_chat or message.from_user
    if not user or not user.id:
        return await word_reply(client, message)
    chat = message.chat
    if not chat or not chat.id:
        return await word_reply(client, message)
    if (
        app_config.agent_whitelist_mode
        and user.id not in app_config.agent_whitelist
        and chat.id not in app_config.agent_whitelist
    ):
        return await word_reply(client, message)
    if chat.type == pyrogram.enums.ChatType.SUPERGROUP:
        chat_config = await database.get_chat_config(chat)
        if not chat_config.ai_reply:
            return await word_reply(client, message)
    user_data = await database.get_user_by_id(user.id)
    if not user_data:
        return
    if await common.memstore.get(state.waiting_key(user.id)):
        return await word_reply(client, message)

    # Check if there's a pending deferred ask
    ask_state = await tools.get_ask_state(chat.id, user.id)
    if ask_state is not None:
        # Resume the deferred ask with "no answer" result
        # Include the new user message so agent can see it (with multimodal support)
        user_prompt, needs_multimodal = await get_input_prompt(
            client, message, include_nearby=0, ctx=None
        )
        user_message_text = message.text or message.caption or ""
        logger.info(
            f"Resuming deferred ask for user {user.id} with no answer, "
            f"user_message='{user_message_text[:50]}...', needs_multimodal={needs_multimodal}"
        )
        await tools.resume_ask(
            client=client,
            ask_state=ask_state,
            answer="用户没有回答，而是发送了新消息",
            message=message,
            powermemory=powermemory,
            user_prompt=user_prompt,
            needs_multimodal=needs_multimodal,
        )
        return

    await common.memstore.set(state.waiting_key(user.id), True)
    # set language
    if chat.type == pyrogram.enums.ChatType.PRIVATE:
        lang = (await database.get_user_config(user.id)).lang
    else:
        lang = (await database.get_chat_config(chat.id)).lang

    # agent run
    try:
        chat_id = chat.id
        history: list[ModelMessage] = await common.memttlcache.get(
            state.history_key(chat_id, user.id), []
        )
        is_group_chat = chat.type in (
            pyrogram.enums.ChatType.SUPERGROUP,
            pyrogram.enums.ChatType.GROUP,
        )
        instructions = (
            app_config.agent_prompt
            if not is_group_chat
            else app_config.agent_group_prompt
            if app_config.agent_group_prompt
            else app_config.agent_prompt
        )
        ctx_info = await build_ctx_info(
            message=message,
            user=user,
            user_data=user_data,
            history=history,
            is_group_chat=is_group_chat,
        )
        if ctx_info:
            instructions += f"\n\n{ctx_info.to_text()}\n"
        # 在群聊场景中获取附近消息作为上下文
        # [TODO] 好像自动添加附近消息反而效果不好了
        nearby_count = (
            app_config.agent_group_context_nearby_message_count if is_group_chat else 0
        )
        user_prompt, _ = await get_input_prompt(
            client, message, include_nearby=nearby_count, ctx=ctx_info
        )
        user_message_text = message.text or message.caption or ""
        if user_message_text:
            logger.debug(
                f"User {user.id} wake agent in Chat {chat.id}: {user_message_text}"
            )
        await utils.cache_user_image(message, chat_id, user.id)
        await run_agent(
            agent_instance=agent,
            client=client,
            message=message,
            user_id=user.id,
            chat_id=chat_id,
            instructions=instructions,
            user_prompt=user_prompt,
            history=history,
            deps=datatype.ContextDeps(
                user_id=user.id,
                chat_id=chat_id,
                message=message,
                client=client,
                powermemory=powermemory,
                history=history,
            ),  # type: ignore
            multimodal_model=multimodal_model,
            model=model,
            lang=lang,
        )
    finally:
        await common.memstore.delete(state.waiting_key(user.id))
