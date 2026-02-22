import asyncio
from datetime import datetime

import pydantic_ai
import pyrogram
from ddgs import DDGS
from powermem import AsyncMemory
from pydantic_ai import Agent, ModelMessage, RunContext, Tool
from pydantic_ai.common_tools.duckduckgo import DuckDuckGoSearchTool
from pydantic_ai.messages import (
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
)
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pyrogram import filters
from pyrogram.client import Client as PyrogramClient

from kmua import affection, common, database, i18n
from kmua.config import app_config
from kmua.logger import logger
from kmua.services import manyacg

from . import datatype, myfilter, state, tools, utils
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
    # 总结历史+更新记忆
    # processor 会在消息发送给模型之前被调用
    assert summary_agent is not None, "summary_agent is not initialized"
    assert memory_agent is not None, "memory_agent is not initialized"
    summary = await utils.summarize_history(summary_agent, messages)
    await common.memttlcache.set(
        state.history_key(ctx.deps.chat_id, ctx.deps.user_id),
        summary,
        ttl=app_config.cachettl_agent_history,
    )
    if len(messages) >= app_config.agent_messages_threshold:
        try:
            history_text = utils.get_history_text(messages)
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
        tools=[
            tools.schedule_message,
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
                tools.search_chat_in_jokes,
                prepare=tools.prepare_group_tools,
            ),
            tools.send_anime_photo,
            Tool(
                tools.search_group_memory,
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
            tools.ask_user,
        ],
        deps_type=datatype.ContextDeps,
        history_processors=[history_processor],
        retries=3,
    )
    summary_agent = Agent(
        model=model, system_prompt=app_config.agent_summary_prompt, retries=3
    )
    memory_agent = Agent(
        retries=3,
        model=model,
        output_type=datatype.UserMemoryResult,
        system_prompt=app_config.agent_memory_prompt,
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
    await tools.cancel_pending_asks(user.id)
    await common.memstore.set(state.waiting_key(user.id), True)
    # set language
    if chat.type == pyrogram.enums.ChatType.PRIVATE:
        lang = (await database.get_user_config(user.id)).lang
    else:
        lang = (await database.get_chat_config(chat.id)).lang

    await message.reply_chat_action(pyrogram.enums.ChatAction.TYPING)
    # agent run
    try:
        chat_id = chat.id
        history: list[ModelMessage] = await common.memttlcache.get(
            state.history_key(chat_id, user.id), []
        )
        instructions = app_config.agent_prompt
        is_group_chat = chat.type in (
            pyrogram.enums.ChatType.SUPERGROUP,
            pyrogram.enums.ChatType.GROUP,
        )
        ctx_info: datatype.ContextInfo | None = None
        if len(history) % 4 == 0:  # 每四次对话发送一次上下文
            ctx_info = datatype.ContextInfo(
                user_data=datatype.UserData(
                    user_id=user.id,
                    full_name=user_data.full_name,
                    username=user_data.username,
                    config={"lang": user_data.user_config.lang}
                    if user_data.user_config
                    else None,
                ),
                chat_type=chat.type.name if chat.type else None,
                msg_id=message.id,
                current_time=datetime.now().isoformat(),
                is_group_chat=is_group_chat,
            )
            if reply_to := message.reply_to_message:
                ctx_info.reply_to_msg_id = reply_to.id
                ctx_info.reply_to_msg_text = reply_to.text or reply_to.caption
            memory = await common.memttlcache.get(state.memory_key(user.id))
            if memory and isinstance(memory, datatype.ChatMemoryy):
                ctx_info.memory_about_user = memory
            affection_rank = await affection.get_affection_rank(user_data.id)
            append_prompt = utils.get_agent_affection_prompt(affection_rank)
            if append_prompt:
                ctx_info.append_prompt = append_prompt
            instructions += f"\n\n{ctx_info.to_text()}\n"
        # 在群聊场景中获取附近消息作为上下文
        nearby_count = 6 if is_group_chat else 0
        user_prompt, needs_multimodal = await utils.get_input_prompt(
            client, message, include_nearby=nearby_count, ctx=ctx_info
        )
        user_message_text = message.text or message.caption or ""
        if user_message_text:
            logger.debug(f"User {user.id} prompt: {user_message_text}")
        try:
            use_model = multimodal_model if needs_multimodal else model
            if app_config.agent_streaming:
                async with agent.iter(
                    instructions=instructions,
                    model=use_model,
                    user_prompt=user_prompt,
                    message_history=history,
                    deps=datatype.ContextDeps(
                        user_id=user.id,
                        chat_id=chat_id,
                        message=message,
                        client=client,
                        powermemory=powermemory,
                        history=history,
                    ),  # type: ignore
                ) as agent_run:
                    streaming_output: utils.StreamingOutput | None = None
                    async for node in agent_run:
                        if Agent.is_model_request_node(node):
                            async with node.stream(agent_run.ctx) as request_stream:
                                async for event in request_stream:
                                    if isinstance(event, PartStartEvent):
                                        if isinstance(event.part, TextPart):
                                            if streaming_output is None:
                                                streaming_output = (
                                                    utils.StreamingOutput(
                                                        client, message
                                                    )
                                                )
                                            await streaming_output.append_delta(
                                                event.part.content
                                            )
                                    elif isinstance(event, PartDeltaEvent):
                                        if isinstance(event.delta, TextPartDelta):
                                            if streaming_output is None:
                                                streaming_output = (
                                                    utils.StreamingOutput(
                                                        client, message
                                                    )
                                                )
                                            await streaming_output.append_delta(
                                                event.delta.content_delta
                                            )
                        elif Agent.is_end_node(node):
                            assert agent_run.result is not None, (
                                "Agent run ended without result"
                            )
                            logger.debug(
                                f"Agent run end with result: {agent_run.result.output}"
                            )
                            if streaming_output is not None:
                                await streaming_output.finalize()
                            elif agent_run.result and agent_run.result.output:
                                await utils.reply_output(
                                    client, message, agent_run.result.output
                                )
            else:
                async with agent.iter(
                    instructions=instructions,
                    model=use_model,
                    user_prompt=user_prompt,
                    message_history=history,
                    deps=datatype.ContextDeps(
                        user_id=user.id,
                        chat_id=chat_id,
                        message=message,
                        client=client,
                        powermemory=powermemory,
                        history=history,
                    ),  # type: ignore
                ) as agent_run:
                    replied = False
                    async for node in agent_run:
                        if Agent.is_call_tools_node(node):
                            for part in node.model_response.parts:
                                if part.part_kind == "text" and part.content:
                                    await utils.reply_output(
                                        client, message, part.content
                                    )
                                    replied = True
                        elif Agent.is_end_node(node):
                            assert agent_run.result is not None, (
                                "Agent run ended without result"
                            )
                            logger.debug(
                                f"Agent run end with result: {agent_run.result.output}"
                            )
                            if not replied and agent_run.result:
                                await utils.reply_output(
                                    client, message, agent_run.result.output
                                )
        except TypeError as e:
            # https://github.com/pydantic/pydantic-ai/issues/527
            # https://github.com/pydantic/pydantic-ai/issues/1813
            # https://github.com/pydantic/pydantic-ai/issues/1746
            logger.exception(f"Agent run error: {e}")
            await message.reply_text(
                f"{i18n.t('bot.msg.agent.errors.too_fast', locale=lang)}\n<code>{e}</code>",
                parse_mode=pyrogram.enums.ParseMode.HTML,
            )
            raise e
        except pydantic_ai.exceptions.ModelHTTPError as e:
            logger.exception(f"Agent HTTP error: {e}")
            if e.status_code == 400:
                await message.reply_text(
                    i18n.t("bot.msg.agent.errors.model_http_400", locale=lang)
                )
                return
            else:
                await message.reply_text(
                    i18n.t("bot.msg.agent.errors.model_http", locale=lang).format(
                        code=e.status_code
                    )
                )
            return
    except Exception as e:
        logger.exception(
            f"Unexpected error in wake_agent: {e.__class__.__name__} - {e}"
        )
    finally:
        await common.memstore.delete(state.waiting_key(user.id))
