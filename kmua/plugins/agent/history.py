from collections import defaultdict

from pydantic_ai import Agent, UserPromptPart
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse

from kmua.config import app_config
from kmua.i18n import i18n
from kmua.logger import logger


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
    return "\n".join(text_lines)


def get_history_token_count(messages: list[ModelMessage]) -> int:
    total = 0
    for msg in messages:
        if isinstance(msg, ModelResponse):
            usage = msg.usage
            total += usage.total_tokens
    return total


def should_compress_by_tokens(messages: list[ModelMessage]) -> bool:
    window = app_config.agent_context_window_tokens
    if not window:
        return False
    ratio = app_config.agent_context_compress_ratio
    threshold_tokens = int(window * ratio)
    current_tokens = get_history_token_count(messages)
    if current_tokens > 0 and current_tokens >= threshold_tokens:
        logger.debug(
            f"Token-based compression triggered: {current_tokens} >= {threshold_tokens} "
            f"({ratio:.0%} of {window} window)"
        )
        return True
    return False


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


async def summarize_history(
    summary_agent: Agent,
    messages: list[ModelMessage],
    messages_threshold: int = app_config.agent_messages_threshold,
) -> list[ModelMessage]:
    if app_config.agent_context_window_tokens:
        if not should_compress_by_tokens(messages):
            return messages
        logger.debug(
            f"Summarizing history: total messages={len(messages)}, "
            f"token_trigger=True (tokens>={int(app_config.agent_context_window_tokens * app_config.agent_context_compress_ratio)})"
        )
    else:
        if len(messages) <= messages_threshold:
            return messages
        logger.debug(
            f"Summarizing history: total messages={len(messages)}, "
            f"count_trigger=True (threshold={messages_threshold})"
        )
    try:
        messages_to_summarize = messages[:-1]
        current_user_message = messages[-1:]

        message_text = get_history_text(messages_to_summarize)

        summary_result = await summary_agent.run(
            user_prompt=f"{i18n.t('bot.msg.agent.summary_prompt', locale=app_config.lang)}: {message_text}",
            message_history=[],
        )
        logger.debug(f"Agent summarize: {summary_result.output}")
        parts = [UserPromptPart(summary_result.output)]
        if current_user_message[0].kind == "request":
            for part in current_user_message[0].parts:
                if part.part_kind == "user-prompt":
                    parts.append(part)
                # [TODO] handle tool call parts

        return [ModelRequest(parts=parts)]
    except Exception as e:
        logger.exception(
            f"Error summarizing history with agent: {e.__class__.__name__} - {e}"
        )
        filtered_messages = filter_tool_return_if_needed(messages[-messages_threshold:])
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
