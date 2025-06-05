from collections import defaultdict

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelRequest, SystemPromptPart

from kmua.config import app_config
from kmua.i18n import i18n
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

    has_multimodal_content = False
    for msg in message_history:
        for part in msg.parts:
            if part.part_kind == "user-prompt" and not isinstance(part.content, str):
                has_multimodal_content = True
                break
        if has_multimodal_content:
            break

    if not has_multimodal_content and len(message_history) <= messages_threshold:
        return message_history

    messages_to_preserve = filter_tool_return_if_needed(
        message_history[-preserve_last_n:]
    )
    try:
        text_lines = []
        added_system_prompt = False
        for msg in message_history:
            for part in msg.parts:
                match part.part_kind:
                    case "system-prompt":
                        if not added_system_prompt:
                            added_system_prompt = True
                            text_lines.append(f"[SYSTEM PROMPT]: {part.content}")
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

        summary_result = await summary_agent.run(
            f"{i18n.t('bot.msg.agent.summary_prompt', locale=app_config.lang)}: {message_text}"
        )
        logger.debug(f"Agent summarize: {summary_result.output}")
        summary_part = SystemPromptPart(
            content=f"[CONVERSATION HISTORY]: {summary_result.output}"
        )

        filtered_preserve_messages = []
        for msg in messages_to_preserve:
            if msg.kind != "request":
                filtered_preserve_messages.append(msg)
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
                filtered_preserve_messages.append(new_msg)

        return [
            *filtered_preserve_messages,
            ModelRequest(parts=[summary_part]),
        ]
    except Exception as e:
        logger.error(f"Error summarizing history with agent {summary_agent.name}: {e}")
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
