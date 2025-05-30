from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelRequest, SystemPromptPart


async def summarize_history(
    summary_agent: Agent,
    message_history: list[ModelMessage],
    preserve_last_n: int = 4,
    messages_threshold: int = 25,
) -> list[ModelMessage]:
    if preserve_last_n >= messages_threshold:
        raise ValueError(
            f"'preserve_last_n' ({preserve_last_n}) must be less than 'messages_threshold' ({messages_threshold})"
        )

    if len(message_history) <= messages_threshold:
        return message_history

    messages_to_preserve = _filter_tool_return_if_needed(
        message_history[-preserve_last_n:]
    )

    summary_result = await summary_agent.run(
        f"Summarize this conversation: {message_history}"
    )

    summary_part = SystemPromptPart(
        content=f"CONVERSATION HISTORY: {summary_result.output}"
    )

    return [
        *messages_to_preserve,
        ModelRequest(parts=[summary_part]),
    ]


def _filter_tool_return_if_needed(messages: list[ModelMessage]) -> list[ModelMessage]:
    filtered_messages: list[ModelMessage] = []
    tool_calls: list[tuple[str, str | None]] = []

    for message in messages:
        for part in message.parts:
            if part.part_kind == "tool-call":
                tool_calls.append((part.tool_name, part.tool_call_id))
                filtered_messages.append(message)
            elif part.part_kind == "tool-return":
                if (part.tool_name, part.tool_call_id) in tool_calls:
                    filtered_messages.append(message)
                    tool_calls.remove((part.tool_name, part.tool_call_id))
            else:
                filtered_messages.append(message)

    return filtered_messages
