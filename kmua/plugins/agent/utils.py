from collections import defaultdict

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelRequest, SystemPromptPart

from kmua.config import app_config
from kmua.logger import logger


async def summarize_history(
    summary_agent: Agent,
    message_history: list[ModelMessage],
    preserve_last_n: int = 4,
    messages_threshold: int = app_config.agent_messages_threshold,
) -> list[ModelMessage]:
    if preserve_last_n >= messages_threshold:
        raise ValueError(
            f"'preserve_last_n' ({preserve_last_n}) must be less than 'messages_threshold' ({messages_threshold})"
        )
    if len(message_history) <= messages_threshold:
        return message_history

    messages_to_preserve = filter_tool_return_if_needed(
        message_history[-preserve_last_n:]
    )
    try:
        summary_result = await summary_agent.run(
            f"Summarize this conversation: {message_history}"
        )
        summary_part = SystemPromptPart(
            content=f"[CONVERSATION HISTORY]: {summary_result.output}"
        )
        return [
            *messages_to_preserve,
            ModelRequest(parts=[summary_part]),
        ]
    except Exception as e:
        logger.error(f"Error summarizing history with agent {summary_agent.name}: {e}")
        return filter_tool_return_if_needed(message_history[-messages_threshold:])


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
