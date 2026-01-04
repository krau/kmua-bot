import asyncio
import random
from dataclasses import dataclass
from datetime import datetime

import pydantic_ai
import pyrogram
import pyrogram.errors
from ddgs import DDGS
from pydantic_ai import Agent, ModelMessage, Tool
from pydantic_ai.common_tools.duckduckgo import DuckDuckGoSearchTool
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pyrogram import filters
from pyrogram.client import Client as PyrogramClient
from pyrogram.enums.parse_mode import ParseMode

from kmua import affection, common, database, enums, i18n
from kmua.common.memory_store import memttlcache
from kmua.config import app_config
from kmua.logger import logger
from kmua.services import manyacg

from . import datatype, myfilter, tools, utils
from .simple_reply import word_reply

agent = None
model = None
multimodal_model = None
summary_agent = None
memory_agent = None

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
        ],
        deps_type=datatype.ContextDeps,
        retries=3,
    )
    summary_agent = Agent(
        model=model, system_prompt=app_config.agent_summary_prompt, retries=3
    )
    memory_agent = Agent(
        retries=3,
        model=model,
        output_type=datatype.MemoryResult,
        system_prompt=app_config.agent_memory_prompt,
    )

    @PyrogramClient.on_message(pyrogram.filters.command("forget"), group=0)
    async def forget_history(client: PyrogramClient, message: pyrogram.types.Message):
        user = message.sender_chat or message.from_user
        if not user or user.id is None:
            return
        user_config = await database.get_user_config(user.id)
        if await common.memstore.get(_waiting_key(user.id)):
            await message.reply_text(
                i18n.t("bot.msg.agent.waiting", locale=user_config.lang)
            )
            return
        chat_id = message.chat.id if message.chat else user.id
        if not chat_id:
            return
        await common.memttlcache.delete(_history_key(chat_id, user.id))
        await message.reply_text(
            i18n.t("bot.msg.agent.forgot", locale=user_config.lang)
        )


def _history_key(chat_id: int, user_id: int) -> str:
    return f"message_history_with_agent:{chat_id}:{user_id}"


def _waiting_key(user_id: int) -> str:
    return f"agent_waiting:{user_id}"


_filter = (
    myfilter.base_filter
    & (myfilter.reply_me_filter | filters.private | myfilter.mention_me_filter)
    & ~pyrogram.filters.regex("|".join([r.pattern for r in manyacg.ARTWORK_ALL_REGEX]))
)


def get_agent_affection_prompt(rank: float) -> str | None:
    prompts = app_config.agent_affection_prompts
    sorted_ranks = sorted(prompts.keys(), reverse=True)
    for r in sorted_ranks:
        if rank >= float(r):
            return prompts[r]
    return None


@PyrogramClient.on_message(_filter, group=0)
async def wake_agent(client: PyrogramClient, message: pyrogram.types.Message):
    try:
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
        if await common.memstore.get(_waiting_key(user.id)):
            return await word_reply(client, message)
        await common.memstore.set(_waiting_key(user.id), True)
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
                _history_key(chat_id, user.id), []
            )
            instructions = app_config.agent_prompt
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
                )
                if reply_to := message.reply_to_message:
                    ctx_info.reply_to_msg_id = reply_to.id
                    ctx_info.reply_to_msg_text = reply_to.text or reply_to.caption
                memory = await common.memttlcache.get(utils.memory_key(user.id))
                if memory and isinstance(memory, datatype.MemoryAboutUser):
                    ctx_info.memory_about_user = memory
                affection_rank = await affection.get_affection_rank(user_data.id)
                append_prompt = get_agent_affection_prompt(affection_rank)
                if append_prompt:
                    ctx_info.append_prompt = append_prompt
                instructions += f"\n\n{ctx_info.to_text()}"
            user_prompt = await utils.get_input_prompt(client, message)
            logger.debug(
                f"User {user.id} prompt without context due to long history: {message.text or message.caption or ''}"
            )
            sent_any_reply = False

            async def _reply_output(text: str):
                nonlocal sent_any_reply
                # 将原始文本按两个换行分割为多个句子
                lines = [line for line in text.split("\n\n") if line.strip()]
                if not lines:
                    return

                # 一次调用最多发送 3 条消息，尽量平均每条消息包含的句子数
                max_messages = 3
                total_sentences = len(lines)
                num_messages = min(max_messages, total_sentences)

                base = total_sentences // num_messages
                remainder = total_sentences % num_messages

                chunks: list[str] = []
                index = 0
                for i in range(num_messages):
                    size = base + (1 if i < remainder else 0)
                    part = lines[index : index + size]
                    index += size
                    # 每条消息内部的句子之间只用一个换行连接
                    chunks.append("\n".join(part))

                try:
                    for chunk in chunks:
                        await message.reply_chat_action(
                            pyrogram.enums.ChatAction.TYPING
                        )
                        await message.reply_text(chunk, parse_mode=ParseMode.DISABLED)
                        await asyncio.sleep(random.uniform(0.721, 3.9))
                    sent_any_reply = True
                except pyrogram.errors.MessageNotModified:
                    pass
                except Exception as e:
                    logger.error(
                        f"Error replying or editing message: {e.__class__.__name__} - {e}"
                    )

            try:
                use_model = (
                    model
                    if not utils.has_multimodal_input(user_prompt)
                    else multimodal_model
                )
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
                    ),  # type: ignore
                ) as agent_run:
                    async for node in agent_run:
                        if Agent.is_call_tools_node(node):
                            for part in node.model_response.parts:
                                if part.part_kind == "text" and part.content:
                                    await _reply_output(part.content)
                        elif Agent.is_end_node(node):
                            if agent_run.result:
                                logger.debug(
                                    f"Agent run end with result: {agent_run.result.output}"
                                )
                                # tool call 阶段的 text part 就是这里最终的 output，不需要重复发送
                                if not sent_any_reply:
                                    await _reply_output(agent_run.result.output)
                                summary = await utils.summarize_history(
                                    summary_agent, agent_run.result.all_messages()
                                )
                                await common.memttlcache.set(
                                    _history_key(chat_id, user.id),
                                    summary,
                                    ttl=app_config.cachettl_agent_history,
                                )
                                if (
                                    len(agent_run.result.all_messages())
                                    >= app_config.agent_messages_threshold
                                ):
                                    # update memory
                                    try:
                                        history_text = utils.get_history_text(
                                            agent_run.result.all_messages()
                                        )
                                        await utils.update_memory(
                                            memory_agent, history_text, user.id
                                        )
                                    except Exception as e:
                                        logger.exception(
                                            f"Error updating memory for user {user.id}: {e.__class__.__name__} - {e}"
                                        )
                            else:
                                logger.error(
                                    f"Agent run ended with no result for user {user.id} in chat {chat_id}"
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

        finally:
            await common.memstore.delete(_waiting_key(user.id))
    except Exception as e:
        logger.exception(
            f"Unexpected error in wake_agent: {e.__class__.__name__} - {e}"
        )


@dataclass
class UserMessageGlobal:
    chat_id: int
    message_id: int
    text: str


@PyrogramClient.on_message(group=100)
async def after_all(client: PyrogramClient, message: pyrogram.types.Message):
    if not agent or not app_config.agent or not app_config.agent_cross_group_memory:
        return
    user = message.from_user
    chat = message.chat
    if not user or not user.id or not chat or not chat.id:
        return
    if (
        user.is_bot
        or message.outgoing
        or message.service
        or message.automatic_forward
        or (
            user.id
            in (
                enums.ChatID.ANONYMOUS_ADMIN,
                enums.ChatID.SERVICE_CHAT,
                enums.ChatID.FAKE_CHANNEL,
            )
        )
    ):
        return
    text = message.caption or message.text
    if not text or len(text) < 12:
        return
    if chat.type in (pyrogram.enums.ChatType.SUPERGROUP, pyrogram.enums.ChatType.GROUP):
        config = await database.get_chat_config(chat.id)
        if not config.ai_reply:
            return
    user_messages: list[UserMessageGlobal] = await memttlcache.get(
        f"user_messages_global:{user.id}", []
    )
    user_messages.append(
        UserMessageGlobal(
            chat_id=chat.id,
            message_id=message.id,
            text=text,
        )
    )
    if len(user_messages) > 100:
        # 只保留最近 100 条
        user_messages = user_messages[-100:]

        # 每个用户每小时最多通过此函数更新一次记忆
        last_update_key = f"user_memory_last_update_from_after_all:{user.id}"
        last_updated = await memttlcache.get(last_update_key)
        if not last_updated:
            texts = "\n".join([um.text for um in user_messages])
            await utils.update_memory(memory_agent, texts, user.id)
            await memttlcache.set(last_update_key, True, ttl=3600)
    await memttlcache.set(
        f"user_messages_global:{user.id}", user_messages, ttl=86400 * 7
    )


if app_config.debug:

    @PyrogramClient.on_message(filters.command("affection"), group=1)
    async def debug_affection(client: PyrogramClient, message: pyrogram.types.Message):
        try:
            user = message.from_user
            if not user or not user.id:
                return
            affection_value = await affection.get_user_affection(user.id)
            rank = await affection.get_affection_rank(user.id)
            logger.info(
                f"User {user.id} affection debug: {affection_value}, rank: {rank:.4f}"
            )
            # add affection
            affection_change = 10
            await affection.update_user_affection(user.id, affection_change)
            now_affection = await affection.get_user_affection(user.id)
            logger.info(
                f"User {user.id} affection debug changed by {affection_change}, now {now_affection}"
            )
        except Exception as e:
            logger.exception(
                f"Unexpected error in debug_affection: {e.__class__.__name__} - {e}"
            )
