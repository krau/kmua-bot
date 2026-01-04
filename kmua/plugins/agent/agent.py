import asyncio
import random
from dataclasses import dataclass
from datetime import datetime

import pydantic_ai
import pyrogram
import pyrogram.errors
from ddgs import DDGS
from pydantic import BaseModel
from pydantic_ai import Agent, ModelMessage, RunContext, Tool
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


async def history_processor(
    ctx: RunContext[datatype.ContextDeps], messages: list[ModelMessage]
) -> list[ModelMessage]:
    # 总结历史+更新记忆
    # processor 会在消息发送给模型之前被调用
    summary = await utils.summarize_history(summary_agent, messages)
    await common.memttlcache.set(
        _history_key(ctx.deps.chat_id, ctx.deps.user_id),
        summary,
        ttl=app_config.cachettl_agent_history,
    )
    if len(messages) >= app_config.agent_messages_threshold:
        try:
            history_text = utils.get_history_text(messages)
            await utils.update_memory(memory_agent, history_text, ctx.deps.user_id)
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
        history_processors=[history_processor],
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


def _bot_last_reply_key(chat_id: int) -> str:
    """存储bot在某个群组最后一条回复的信息"""
    return f"bot_last_reply:{chat_id}"


def _message_follow_up_lock_key(message_id: int) -> str:
    """防止对同一条消息重复处理follow-up"""
    return f"message_follow_up_lock:{message_id}"


@dataclass
class BotLastReply:
    """记录bot最近的回复信息"""

    message_id: int
    reply_to_user_id: int
    reply_to_message_id: int
    reply_text: str
    timestamp: float
    original_user_message: str = ""  # 原始用户消息文本


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
            memory = await common.memttlcache.get(utils.memory_key(user.id))
            if memory and isinstance(memory, datatype.MemoryAboutUser):
                ctx_info.memory_about_user = memory
            affection_rank = await affection.get_affection_rank(user_data.id)
            append_prompt = get_agent_affection_prompt(affection_rank)
            if append_prompt:
                ctx_info.append_prompt = append_prompt
            instructions += f"\n\n{ctx_info.to_text()}"
        # 在群聊场景中获取附近消息作为上下文
        nearby_count = 11 if is_group_chat else 0
        user_prompt = await utils.get_input_prompt(
            client, message, include_nearby=nearby_count, ctx=ctx_info
        )
        logger.debug(f"User {user.id} prompt: {message.text or message.caption or ''}")
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
                    await message.reply_chat_action(pyrogram.enums.ChatAction.TYPING)
                    reply_msg = await message.reply_text(
                        chunk, parse_mode=ParseMode.DISABLED
                    )
                    # 记录bot的回复用于后续的follow-up检测
                    if reply_msg and is_group_chat and user.id:
                        bot_reply = BotLastReply(
                            message_id=reply_msg.id,
                            reply_to_user_id=user.id,
                            reply_to_message_id=message.id,
                            reply_text=chunk,
                            timestamp=datetime.now().timestamp(),
                            original_user_message=message.text or message.caption or "",
                        )
                        await common.memttlcache.set(
                            _bot_last_reply_key(chat_id),
                            bot_reply,
                            ttl=600,  # 10分钟内的follow-up消息会被检测
                        )
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
                        assert agent_run.result is not None, (
                            "Agent run ended without result"
                        )
                        logger.debug(
                            f"Agent run end with result: {agent_run.result.output}"
                        )
                        # tool call 阶段的 text part 就是这里最终的 output，不需要重复发送
                        if not sent_any_reply:
                            await _reply_output(agent_run.result.output)
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
        await common.memstore.delete(_waiting_key(user.id))


class RelevanceCheck(BaseModel):
    is_relevant: bool
    confidence: float  # 0-1之间的置信度
    reason: str = ""


@PyrogramClient.on_message(group=15)
async def handle_follow_up_message(
    client: PyrogramClient, message: pyrogram.types.Message
):
    """检测用户消息是否是对bot回复的follow-up，如果是则主动回复"""
    # 基础检查
    if not agent or not model or not app_config.agent:
        return

    if not message.chat or not message.chat.id:
        return

    # 仅在群聊中处理
    if message.chat.type not in (
        pyrogram.enums.ChatType.SUPERGROUP,
        pyrogram.enums.ChatType.GROUP,
    ):
        return

    # 检查此消息是否已处理过follow-up
    if await common.memttlcache.get(_message_follow_up_lock_key(message.id)):
        return
    await common.memttlcache.set(_message_follow_up_lock_key(message.id), True, ttl=60)

    chat_id = message.chat.id
    user = message.sender_chat or message.from_user

    # 排除不应该处理的消息
    if (
        not user
        or not user.id
        or message.outgoing
        or message.service
        or message.automatic_forward
        or message.reply_to_message  # 已经是回复消息，不处理
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

    # 检查是否有 @ 提及（如果有则说明是主动提及，不需要 follow-up 处理）
    if message.entities:
        has_mention = any(
            entity.type == pyrogram.enums.MessageEntityType.MENTION
            or entity.type == pyrogram.enums.MessageEntityType.TEXT_MENTION
            for entity in message.entities
        )
        if has_mention:
            return

    # 检查是否有bot最近的回复
    bot_reply = await common.memttlcache.get(_bot_last_reply_key(chat_id))
    if not bot_reply or not isinstance(bot_reply, BotLastReply):
        return

    # 检查消息距离bot回复的时间间隔（不超过10分钟）
    if not message.date:
        return
    time_diff = message.date.timestamp() - bot_reply.timestamp
    if time_diff < 0 or time_diff > 600:  # 10分钟
        return

    # 检查消息是否与bot回复相关（需要调用AI判断）
    message_text = message.text or message.caption or ""
    if not message_text or len(message_text) < 3:
        return

    try:
        relevance_check_agent = Agent(
            model=model,
            output_type=RelevanceCheck,
            system_prompt="你是一个对话相关性判断助手。判断用户的新消息是否是对之前对话的延续。",
            retries=2,
        )

        relevance_check_prompt = f"""
原始对话:
用户A: {bot_reply.original_user_message}
Bot回复: {bot_reply.reply_text}

现在收到了某用户发送的新消息: {message_text}

判断这条新消息是否是对Bot回复的评论、疑问、补充、反驳或相关讨论。
注意：即使是不同用户发送的消息也可能相关。
"""
        relevance_result = await relevance_check_agent.run(
            user_prompt=relevance_check_prompt,
        )

        # 只有当置信度较高时才触发 follow-up
        if (
            not relevance_result.output.is_relevant
            or relevance_result.output.confidence < 0.6
        ):
            return

        logger.info(
            f"Detected follow-up message {message.id} (confidence: {relevance_result.output.confidence}, reason: {relevance_result.output.reason})"
        )

        # 相关
        user_data = await database.get_user_by_id(user.id)
        if not user_data:
            return

        chat_config = await database.get_chat_config(message.chat)
        if not chat_config.ai_reply:
            return

        # 防止spam：检查是否正在处理其他消息
        if await common.memstore.get(_waiting_key(user.id)):
            return

        await common.memstore.set(_waiting_key(user.id), True)
        await message.reply_chat_action(pyrogram.enums.ChatAction.TYPING)

        try:
            # 获取上下文信息
            ctx_info = datatype.ContextInfo(
                user_data=datatype.UserData(
                    user_id=user.id,
                    full_name=user_data.full_name,
                    username=user_data.username,
                    config={"lang": user_data.user_config.lang}
                    if user_data.user_config
                    else None,
                ),
                chat_type=message.chat.type.name if message.chat.type else None,
                msg_id=message.id,
                current_time=datetime.now().isoformat(),
                is_group_chat=True,
            )

            # 构建包含完整上下文的 prompt
            follow_up_prompt = await utils.get_input_prompt(
                client, message, include_nearby=5, ctx=ctx_info
            )

            # 添加对话历史上下文到 instructions
            follow_up_instructions = (
                app_config.agent_prompt
                + f"""

重要上下文：刚才有一段对话
用户: {bot_reply.original_user_message}
你的回复: {bot_reply.reply_text}

现在又有人对这个话题继续讨论，请自然地参与对话。
"""
            )

            # 调用agent处理follow-up消息
            history: list[ModelMessage] = []
            use_model = (
                model
                if not utils.has_multimodal_input(follow_up_prompt)
                else multimodal_model
            )

            sent_any_reply = False

            async def _reply_output(text: str):
                nonlocal sent_any_reply
                lines = [line for line in text.split("\n\n") if line.strip()]
                if not lines:
                    return

                max_messages = 2
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
                    chunks.append("\n".join(part))

                try:
                    for chunk in chunks:
                        await message.reply_chat_action(
                            pyrogram.enums.ChatAction.TYPING
                        )
                        await message.reply_text(chunk, parse_mode=ParseMode.DISABLED)
                        await asyncio.sleep(random.uniform(0.5, 2.0))
                    sent_any_reply = True
                except Exception as e:
                    logger.error(
                        f"Error replying follow-up message: {e.__class__.__name__} - {e}"
                    )

            async with agent.iter(
                instructions=follow_up_instructions,
                model=use_model,
                user_prompt=follow_up_prompt,
                message_history=history,
                deps=datatype.ContextDeps(
                    user_id=user.id,
                    chat_id=chat_id,
                    message=message,
                    client=client,
                ),
            ) as agent_run:
                async for node in agent_run:
                    if Agent.is_call_tools_node(node):
                        for part in node.model_response.parts:
                            if part.part_kind == "text" and part.content:
                                await _reply_output(part.content)
                    elif Agent.is_end_node(node):
                        if not sent_any_reply and agent_run.result:
                            await _reply_output(agent_run.result.output)

        except Exception as e:
            logger.exception(
                f"Error handling follow-up message: {e.__class__.__name__} - {e}"
            )
        finally:
            await common.memstore.delete(_waiting_key(user.id))

    except Exception as e:
        logger.exception(
            f"Error checking message relevance: {e.__class__.__name__} - {e}"
        )


@dataclass
class UserMessageGlobal:
    chat_id: int
    message_id: int
    text: str


@PyrogramClient.on_message(group=100)
async def record_cross_group_memory(
    client: PyrogramClient, message: pyrogram.types.Message
):
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
        or message.forward_from_chat
        or message.forward_from
        or message.forward_sender_name
        or message.via_bot
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
        user_messages = user_messages[-100:]
        # 每个用户每小时最多通过此函数更新一次记忆
        last_update_key = f"user_memory_last_update_from_after_all:{user.id}"
        last_updated = await memttlcache.get(last_update_key)
        if not last_updated:
            await memttlcache.set(last_update_key, True, ttl=3600)
            texts = "\n".join([um.text for um in user_messages])
            await utils.update_memory(memory_agent, texts, user.id)
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
