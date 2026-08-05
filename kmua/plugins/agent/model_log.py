from typing import Any

from pydantic_ai import ModelResponse, RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import TextPart, ToolCallPart
from pydantic_ai.models import ModelRequestContext

from kmua.logger import logger

_TEXT_LIMIT = 200


def _label(deps: Any) -> str:
    """Owner label ('user 123 in chat -100'); empty when deps carry neither."""
    if deps is None:
        return ""
    user_id = getattr(deps, "user_id", None)
    chat_id = getattr(deps, "chat_id", None)
    parts = []
    if user_id is not None:
        parts.append(f"user {user_id}")
    if chat_id is not None:
        parts.append(f"chat {chat_id}")
    return " in ".join(parts)


def _truncate(text: str, limit: int = _TEXT_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


class ModelActivityLog(AbstractCapability[Any]):
    async def before_model_request(
        self,
        ctx: RunContext[Any],
        request_context: ModelRequestContext,
    ) -> ModelRequestContext:
        model_name = getattr(request_context.model, "model_name", None) or (
            request_context.model_id or type(request_context.model).__name__
        )
        tool_returns = sum(
            1
            for msg in request_context.messages
            for part in getattr(msg, "parts", ())
            if getattr(part, "part_kind", None) == "tool-return"
        )
        user_prompt = ""
        for msg in reversed(request_context.messages):
            for part in reversed(getattr(msg, "parts", ())):
                if getattr(part, "part_kind", None) == "user-prompt":
                    user_prompt = _truncate(str(getattr(part, "content", "")))
                    break
            if user_prompt:
                break
        label = _label(ctx.deps)
        owner = f" for {label}" if label else ""
        prompt_part = f', user_prompt="{user_prompt}"' if user_prompt else ""
        logger.debug(
            f"model request{owner}: model={model_name} "
            f"messages={len(request_context.messages)} tool_returns={tool_returns}"
            f"{prompt_part}"
        )
        return request_context

    async def after_model_request(
        self,
        ctx: RunContext[Any],
        *,
        request_context: ModelRequestContext,
        response: ModelResponse,
    ) -> ModelResponse:
        tools: list[str] = []
        text_parts: list[str] = []
        for part in response.parts:
            if isinstance(part, ToolCallPart):
                tools.append(f"{part.tool_name}({_truncate(str(part.args))})")
            elif isinstance(part, TextPart):
                if part.content:
                    text_parts.append(str(part.content))
        details: list[str] = []
        if tools:
            details.append("tools=" + "; ".join(tools))
        if text_parts:
            details.append(f'text="{_truncate(" ".join(text_parts))}"')
        label = _label(ctx.deps)
        owner = f" for {label}" if label else ""
        logger.debug(
            f"model response{owner}: "
            + (", ".join(details) if details else "no output parts")
        )
        return response

    async def on_model_request_error(
        self,
        ctx: RunContext[Any],
        *,
        request_context: ModelRequestContext,
        error: Exception,
    ) -> ModelResponse:
        label = _label(ctx.deps)
        owner = f" for {label}" if label else ""
        logger.debug(
            f"model request failed{owner}: {error.__class__.__name__}: {error}"
        )
        raise error
