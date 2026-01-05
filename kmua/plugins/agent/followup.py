from datetime import datetime

import pyrogram
from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelMessage
from pyrogram.client import Client as PyrogramClient

from kmua import affection, common, database, enums
from kmua.common.memory_store import memttlcache
from kmua.config import app_config
from kmua.logger import logger
from kmua.plugins.agent import datatype, state, utils

from .agent import agent, powermemory, small_model


class RelevanceCheck(BaseModel):
    relevance: bool = Field(description="是否相关")
    reason: str = Field(description="判断依据说明")


if small_model:
    relevance_check_agent = Agent(
        model=small_model,
        output_type=RelevanceCheck,
        system_prompt="你是一个对话相关性判断助手。判断用户的新消息是否是对之前对话的延续。",
        retries=2,
    )


async def _follow_up_filter_func(
    _, client: PyrogramClient, message: pyrogram.types.Message
) -> bool:
    if not app_config.agent or not app_config.agent_follow_up:
        return False
    if not relevance_check_agent:
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
    if await common.memstore.get(state.waiting_key(user.id)):
        return False
    return True


follow_up_filter = pyrogram.filters.create(_follow_up_filter_func)


@PyrogramClient.on_message(follow_up_filter, group=10)
async def handle_follow_up_message(
    client: PyrogramClient, message: pyrogram.types.Message
):
    chat = message.chat
    user = message.sender_chat or message.from_user
    assert chat is not None and chat.id is not None, "Invalid chat in follow-up"
    assert user is not None and user.id is not None, "Invalid user in follow-up"
    if await common.memttlcache.get(
        state.message_follow_up_lock_key(chat.id, message.id)
    ):
        return
    await common.memttlcache.set(
        state.message_follow_up_lock_key(chat.id, message.id), True, ttl=60
    )
    bot_reply = await common.memttlcache.get(state.bot_last_reply_key(chat.id))
    if not bot_reply or not isinstance(bot_reply, datatype.BotLastReply):
        return False
    if not message.date:
        return False
    time_diff = message.date.timestamp() - bot_reply.timestamp
    if time_diff < 0 or time_diff > 300:
        return False
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
    relevance_check_prompt = f"""
在群聊场景中发生如下原始对话:
用户: {bot_reply.original_user_message}
Bot回复: {bot_reply.reply_text}

现在收到了某用户发送的新消息: {message_text}

判断这条新消息是否是对Bot回复的评论、疑问、补充、反驳或相关讨论.
注意：
- 即使是不同用户发送的消息也可能相关
- 新消息与原先话题必须存在明显的关联性才算相关, 如果不能确定, 一律判定为不相关
"""
    try:
        relevance_result = await relevance_check_agent.run(
            user_prompt=relevance_check_prompt,
        )
        if not relevance_result.output.relevance:
            return
    except Exception as e:
        logger.error(
            f"Error checking follow-up relevance: {e.__class__.__name__} - {e}"
        )
        return
    logger.info(
        f"Detected follow-up message {message.id} (reason: {relevance_result.output.reason})"
    )
    if await common.memstore.get(state.waiting_key(user.id)):
        return
    await common.memstore.set(state.waiting_key(user.id), True)
    await message.reply_chat_action(pyrogram.enums.ChatAction.TYPING)

    try:
        history: list[ModelMessage] = await memttlcache.get(
            state.history_key(chat.id, user.id), []
        )
        instructions = (
            app_config.agent_prompt
            + f"""
场景信息: 在群聊中刚才有用户与你进行了对话，内容如下:
用户[{reply_to_user.full_name}]: {bot_reply.original_user_message}
你的回复: {bot_reply.reply_text}
---
现在又有用户[{user_data.full_name}]对这个话题继续讨论，请自然地参与对话。
"""
        )
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
            is_group_chat=True,
        )
        memory = await memttlcache.get(state.memory_key(user.id))
        if memory and isinstance(memory, datatype.ChatMemoryy):
            ctx_info.memory_about_user = memory
        affection_rank = await affection.get_affection_rank(user.id)
        append_prompt = utils.get_agent_affection_prompt(affection_rank)
        if append_prompt:
            ctx_info.append_prompt = append_prompt
        instructions += f"\n\n{ctx_info.to_text()}\n"
        follow_up_prompt = await utils.get_input_prompt(
            client, message, include_nearby=0, ctx=ctx_info
        )
        async with agent.iter(
            instructions=instructions,
            user_prompt=follow_up_prompt,
            message_history=history,
            deps=datatype.ContextDeps(
                user_id=user.id,
                chat_id=chat.id,
                message=message,
                client=client,
                powermemory=powermemory,
            ),
        ) as agent_run:
            repiled = False
            async for node in agent_run:
                if Agent.is_call_tools_node(node):
                    for part in node.model_response.parts:
                        if part.part_kind == "text" and part.content:
                            await utils.reply_output(client, message, part.content)
                            repiled = True
                elif Agent.is_end_node(node):
                    assert agent_run.result is not None, (
                        "Agent run ended without result"
                    )
                    logger.debug(
                        f"Agent follow up run end with result: {agent_run.result.output}"
                    )
                    if not repiled and agent_run.result:
                        await utils.reply_output(
                            client, message, agent_run.result.output
                        )

    except Exception as e:
        logger.exception(
            f"Error handling follow-up message: {e.__class__.__name__} - {e}"
        )
    finally:
        await common.memstore.delete(state.waiting_key(user.id))
