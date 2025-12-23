import asyncio
from collections import defaultdict
from weakref import WeakValueDictionary

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelRequest, SystemPromptPart

from kmua.common.memory_store import memttlcache
from kmua.config import app_config
from kmua.i18n import i18n
from kmua.logger import logger
from kmua.plugins.agent import datatype


def get_history_text(message_history: list[ModelMessage]) -> str:
    text_lines = []
    for msg in message_history:
        for part in msg.parts:
            match part.part_kind:
                case "user-prompt":
                    if isinstance(part.content, str):
                        text_lines.append(f"[USER]: {part.content}")
                    else:
                        content_text_lines = []
                        for content in part.content:
                            if isinstance(content, str):
                                content_text_lines.append(content)
                        text_lines.append(f"[USER]: {' '.join(content_text_lines)}")
                case "text":
                    if msg.kind == "response":
                        text_lines.append(f"[ASSISTANT]: {part.content}")
                case "tool-call":
                    text_lines.append(
                        f"[TOOL {part.tool_name} CALLED WITH ARGS]: {part.args}"
                    )
                case "tool-return":
                    text_lines.append(
                        f"[TOOL {part.tool_name} RETURNED]: {part.content}"
                    )
                case "retry-prompt":
                    pass
    message_text = "\n".join(text_lines)
    return message_text


async def summarize_history(
    summary_agent: Agent,
    message_history: list[ModelMessage],
    messages_threshold: int = app_config.agent_messages_threshold,
) -> list[ModelMessage]:
    has_multimodal_content = False
    for msg in message_history:
        for part in msg.parts:
            if part.part_kind == "user-prompt" and not isinstance(part.content, str):
                for content in part.content:
                    if not isinstance(content, str):
                        has_multimodal_content = True
                        break
        if has_multimodal_content:
            break

    if not has_multimodal_content and len(message_history) <= messages_threshold:
        # 有多模态内容时, 强制总结历史消息
        return message_history

    logger.debug(
        f"Summarizing history: total messages={len(message_history)}, messages_threshold={messages_threshold}"
    )
    try:
        message_text = get_history_text(message_history)

        summary_result = await summary_agent.run(
            user_prompt=f"{i18n.t('bot.msg.agent.summary_prompt', locale=app_config.lang)}: {message_text}"
        )
        logger.debug(f"Agent summarize: {summary_result.output}")
        summary_part = SystemPromptPart(
            content=f"[CONVERSATION HISTORY]: {summary_result.output}"
        )

        return [
            ModelRequest(parts=[summary_part]),
        ]
    except Exception as e:
        logger.exception(
            f"Error summarizing history with agent: {e.__class__.__name__} - {e}"
        )
        filtered_messages = filter_tool_return_if_needed(
            message_history[-messages_threshold:]
        )

        result_messages = []
        for msg in filtered_messages:
            if msg.kind != "request":
                result_messages.append(msg)
                continue

            filtered_parts = []
            for part in msg.parts:
                if part.part_kind == "user-prompt" and not isinstance(
                    part.content, str
                ):
                    continue
                filtered_parts.append(part)

            if filtered_parts:
                new_msg = ModelRequest(parts=filtered_parts)
                result_messages.append(new_msg)

        return result_messages


def filter_tool_return_if_needed(messages: list[ModelMessage]) -> list[ModelMessage]:
    filtered_messages: list[ModelMessage] = []

    tool_calls: defaultdict[str, list[tuple[str, int, ModelMessage]]] = defaultdict(
        list
    )

    for msg_idx, message in enumerate(messages):
        for part in message.parts:
            if part.part_kind == "tool-call" or part.part_kind == "tool-return":
                tool_calls[part.tool_call_id].append((part.part_kind, msg_idx, message))

    messages_to_include = set()

    for tool_call_id, entries in tool_calls.items():
        calls = [e for e in entries if e[0] == "tool-call"]
        returns = [e for e in entries if e[0] == "tool-return"]

        if len(calls) == len(returns) and len(calls) > 0:
            for _, msg_idx, message in entries:
                messages_to_include.add(msg_idx)

    for msg_idx, message in enumerate(messages):
        has_tool_parts = any(
            part.part_kind in ("tool-call", "tool-return") for part in message.parts
        )

        if has_tool_parts:
            if msg_idx in messages_to_include:
                filtered_messages.append(message)
        else:
            filtered_messages.append(message)

    return filtered_messages


_user_memory_locks: WeakValueDictionary[int, asyncio.Lock] = WeakValueDictionary()
_user_memory_locks_lock = asyncio.Lock()


async def _get_user_memory_lock(user_id: int) -> asyncio.Lock:
    async with _user_memory_locks_lock:
        lock = _user_memory_locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            _user_memory_locks[user_id] = lock
        return lock


async def update_memory(
    agent: Agent[None, datatype.MemoryAboutUser],
    message_text: str,
    user_id: int,
):
    lock = await _get_user_memory_lock(user_id)
    async with lock:
        logger.debug(f"Updating memory for user {user_id}")
        old = await memttlcache.get(f"user_memory_{user_id}")
        if old:
            message_text = f"根据已有的记忆和新的聊天消息, 更新对用户的记忆. 旧的记忆: {old}\n新的聊天消息: {message_text}"
        memory_result = await agent.run(
            output_type=datatype.MemoryAboutUser,
            user_prompt=f"根据以下聊天消息, 总结出关于用户的重要信息, 并更新对用户的记忆:\n {message_text}",
        )
        logger.debug(f"Agent memory history: {memory_result.output}")
        await memttlcache.set(
            f"user_memory_{user_id}",
            memory_result.output,
            ttl=86400 * 30,  # 30 days
        )
