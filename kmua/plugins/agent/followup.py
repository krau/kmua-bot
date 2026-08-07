import asyncio

import pyrogram
from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelMessage
from pyrogram.client import Client as PyrogramClient

from kmua import common, database, enums
from kmua.common.memory_store import memttlcache
from kmua.common.utils import is_explicit_reply
from kmua.config import app_config
from kmua.logger import logger
from kmua.plugins.agent import datatype, provider, state
from kmua.plugins.agent.prompt import build_ctx_info, get_input_prompt
from kmua.plugins.agent.runner import (
    get_chat_model_override,
    run_agent,
)

from .agent import (
    _queue_interjection,
    _run_registered,
    agent,
    model,
    multimodal_model,
    powermemory,
    small_model,
)
from .tools import block as tools
from .whitelist import is_chat_allowed


class RelevanceCheck(BaseModel):
    relevance: bool = Field(description="是否相关")
    reason: str = Field(description="判断依据说明")


if small_model:
    _default_relevance_check_agent = Agent(
        model=small_model or model,
        model_settings=provider.make_model_settings(
            app_config.agent_model_small_options
        ),
        output_type=RelevanceCheck,
        system_prompt="你是一个对话相关性判断助手。判断用户的新消息是否是对之前对话的延续。",
        retries=2,
    )
else:
    _default_relevance_check_agent = None


def _make_relevance_check_agent(
    override_model_spec: str | None,
) -> Agent[None, RelevanceCheck] | None:
    """Return a relevance-check agent using the per-chat small model override if set,
    otherwise fall back to the module-level default (which uses the global small_model)."""
    if override_model_spec:
        return Agent(
            model=provider.make_chat_model(override_model_spec),
            model_settings=provider.make_model_settings(
                app_config.agent_model_small_options
            ),
            output_type=RelevanceCheck,
            system_prompt="你是一个对话相关性判断助手。判断用户的新消息是否是对之前对话的延续。",
            retries=2,
        )
    return _default_relevance_check_agent


async def _follow_up_filter_func(
    _, client: PyrogramClient, message: pyrogram.types.Message
) -> bool:
    if not app_config.agent or not app_config.agent_follow_up:
        return False
    if not _default_relevance_check_agent:
        return False
    if not message or not message.chat:
        return False
    chat = message.chat
    if chat.type not in (
        pyrogram.enums.ChatType.SUPERGROUP,
        pyrogram.enums.ChatType.GROUP,
    ):
        return False
    if not chat.id:
        return False
    if not is_chat_allowed(chat.id):
        return False
    text = message.text or message.caption
    if not text or len(text.strip()) == 0:
        return False
    if (
        message.entities is not None
        and message.entities[0].type == pyrogram.enums.MessageEntityType.BOT_COMMAND
    ):
        return False
    if text.startswith("/") or text.startswith("\\"):
        return False
    user = message.sender_chat or message.from_user
    if (
        not user
        or not user.id
        or message.outgoing
        or message.service
        or message.automatic_forward
        or is_explicit_reply(message)  # 已经是用户主动回复的消息，不处理
        or (
            user.id
            in (
                enums.ChatID.ANONYMOUS_ADMIN,
                enums.ChatID.SERVICE_CHAT,
                enums.ChatID.FAKE_CHANNEL,
            )
        )
    ):
        return False
    # 检查是否有 @ 提及（如果有则说明是主动提及，不需要 follow-up 处理）
    if message.entities:
        has_mention = any(
            entity.type == pyrogram.enums.MessageEntityType.MENTION
            or entity.type == pyrogram.enums.MessageEntityType.TEXT_MENTION
            for entity in message.entities
        )
        if has_mention:
            return False
    if chat is not None and chat.id is not None and state.is_running(chat.id, user.id):
        # Mid-turn: the message is an interjection, not a follow-up trigger.
        # Deliver it straight into the live run (budget-checked), so the
        # running turn picks it up on its next model request.
        text = (message.text or message.caption or "").strip()
        if text and not state.enqueue_interjection(chat.id, user.id, text):
            logger.warning(
                f"Follow-up interjection dropped for user {user.id} in "
                f"chat {chat.id}: interjection budget exhausted"
            )
        return False
    return True


follow_up_filter = pyrogram.filters.create(_follow_up_filter_func)


@PyrogramClient.on_message(follow_up_filter, group=10)
async def handle_follow_up_message(
    client: PyrogramClient, message: pyrogram.types.Message
):
    if not app_config.agent or agent is None or model is None:
        return
    chat = message.chat
    user = message.sender_chat or message.from_user
    assert chat is not None and chat.id is not None, "Invalid chat in follow-up"
    assert user is not None and user.id is not None, "Invalid user in follow-up"
    if not is_chat_allowed(chat.id):
        return
    if await tools.is_user_blocked(user.id):
        return
    if await common.memttlcache.get(
        state.message_follow_up_lock_key(chat.id, message.id)
    ):
        return
    await common.memttlcache.set(
        state.message_follow_up_lock_key(chat.id, message.id), True, ttl=60
    )
    bot_reply = await common.memttlcache.get(state.bot_last_reply_key(chat.id))
    if not bot_reply or not isinstance(bot_reply, datatype.BotLastReply):
        return
    if not message.date:
        return
    time_diff = message.date.timestamp() - bot_reply.timestamp
    if time_diff < 0 or time_diff > 300:
        return
    if message.id - bot_reply.message_id > 3:
        return
    chat_config = await database.get_chat_config(chat.id)
    if not chat_config.ai_reply:
        return
    user_data = await database.get_user_by_id(user.id)
    if not user_data:
        return
    reply_to_user = await database.get_user_by_id(bot_reply.reply_to_user_id)
    if not reply_to_user:
        return
    # 调用AI判断相关性
    message_text = message.text or message.caption
    # 使用 full_output（模型的完整输出）而不是 reply_text（可能只是最后一条消息）
    bot_full_output = (
        bot_reply.full_output if bot_reply.full_output else bot_reply.reply_text
    )
    relevance_check_prompt = f"""
在群聊场景中发生如下原始对话:
用户: {bot_reply.original_user_message}
Bot回复: {bot_full_output}

现在收到了某用户发送的新消息: {message_text}

判断这条新消息是否是对Bot回复的评论、疑问、补充、反驳或相关讨论.
注意：
- 即使是不同用户发送的消息也可能相关
- 新消息与原先话题必须存在明显的关联性才算相关, 如果不能确定, 一律判定为不相关
"""
    try:
        small_model_override = await get_chat_model_override(chat.id, "small")
        relevance_check_agent = _make_relevance_check_agent(small_model_override)
        if not relevance_check_agent:
            return

        # 使用小模型超时控制防止相关性检查阻塞事件循环
        timeout = app_config.agent_small_model_timeout
        coro = relevance_check_agent.run(
            user_prompt=relevance_check_prompt,
        )

        if timeout > 0:
            try:
                relevance_result = await asyncio.wait_for(coro, timeout=timeout)
            except TimeoutError:
                logger.warning(f"Follow-up relevance check timed out after {timeout}s")
                return
        else:
            relevance_result = await coro

        if not relevance_result.output.relevance:  # type: ignore[union-attr]
            return
    except Exception as e:
        logger.error(
            f"Error checking follow-up relevance: {e.__class__.__name__} - {e}"
        )
        return
    logger.info(
        f"Detected follow-up message {message.id} (reason: {relevance_result.output.reason})"  # type: ignore[union-attr]
    )
    follow_lock = state.get_conversation_lock(chat.id, user.id)
    if follow_lock.locked():
        await _queue_interjection(message, chat.id, user.id)
        return
    await follow_lock.acquire()
    try:
        await message.reply_chat_action(pyrogram.enums.ChatAction.TYPING)
        instructions = (
            app_config.agent_group_prompt
            if app_config.agent_group_prompt
            else app_config.agent_prompt
        )
        chat_prompt = await memttlcache.get(state.chat_prompt_override_key(chat.id))
        if chat_prompt:
            instructions = chat_prompt
        history: list[ModelMessage] = await memttlcache.get(
            state.history_key(chat.id, user.id), []
        )
        ctx_info = await build_ctx_info(
            message=message,
            user=user,
            user_data=user_data,
            history=history,
            is_group_chat=True,
        )
        follow_up_prompt, _ = await get_input_prompt(
            client, message, include_nearby=0, ctx=None
        )
        addtional_instructions = ctx_info.to_text() if ctx_info else ""
        # 使用 full_output（模型的完整输出）而不是 reply_text
        bot_full_output = (
            bot_reply.full_output if bot_reply.full_output else bot_reply.reply_text
        )
        addtional_instructions += f"""
场景信息: 在群聊中刚才有用户与你进行了对话，内容如下:
用户[{reply_to_user.full_name}]: {bot_reply.original_user_message}
你的回复: {bot_full_output}
---
现在又有用户[{user_data.full_name}]对这个话题继续讨论，请自然地参与对话。
"""
        await _run_registered(
            chat.id,
            user.id,
            run_agent(
                agi=agent,
                additional_instructions=addtional_instructions,
                client=client,
                message=message,
                user_id=user.id,
                chat_id=chat.id,
                user_prompt=follow_up_prompt,
                history=history,
                deps=datatype.ContextDeps(
                    user_id=user.id,
                    chat_id=chat.id,
                    message=message,
                    client=client,
                    instructions=instructions,
                    powermemory=powermemory,
                    history=history,
                ),
                multimodal_model=multimodal_model,
                model=model,
                lang=chat_config.lang,
            ),
        )

    except Exception as e:
        logger.exception(
            f"Error handling follow-up message: {e.__class__.__name__} - {e}"
        )
    finally:
        follow_lock.release()
