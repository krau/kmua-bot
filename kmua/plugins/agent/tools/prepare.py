from collections.abc import Awaitable, Callable

from pydantic_ai import RunContext
from pydantic_ai.tools import ToolDefinition

from kmua import database
from kmua.config import app_config
from kmua.logger import logger
from kmua.plugins.agent import datatype
from kmua.services import image_gen

PrepareFunc = Callable[
    [RunContext[datatype.ContextDeps], ToolDefinition],
    Awaitable[ToolDefinition | None],
]


def compose_prepare(*funcs: PrepareFunc) -> PrepareFunc:
    """Compose multiple prepare functions. Returns the first None, or the tool_def if all pass."""

    async def _composed(
        ctx: RunContext[datatype.ContextDeps], tool_def: ToolDefinition
    ) -> ToolDefinition | None:
        for f in funcs:
            result = await f(ctx, tool_def)
            if result is None:
                return None
        return tool_def

    return _composed


async def prepare_not_guest_mode(
    ctx: RunContext[datatype.ContextDeps], tool_def: ToolDefinition
) -> ToolDefinition | None:
    """Hide the tool when running in guest mode."""
    if ctx.deps.is_guest_mode:
        return None
    return tool_def


async def prepare_manyacg_tools(
    ctx: RunContext[datatype.ContextDeps], tool_def: ToolDefinition
) -> ToolDefinition | None:
    """Show manyacg-backed tools only when the API key is configured."""
    if app_config.manyacg_api_key:
        return tool_def
    return None


async def prepare_sticker_tools(
    ctx: RunContext[datatype.ContextDeps], tool_def: ToolDefinition
) -> ToolDefinition | None:
    """Show the sticker tool only in group chats with a usable sticker memory."""
    if not app_config.agent_sticker_memory:
        return None
    if ctx.deps.chat_id is None or ctx.deps.chat_id >= -100:
        return None
    try:
        from .. import sticker_memory, sticker_vec

        if sticker_memory.embedder is None:
            return None
        target = app_config.agent_sticker_warmup_count
        if target is not None and target > 0:
            count = await sticker_vec.count(ctx.deps.chat_id)
            if count < target:
                return None
        if not (
            await database.get_chat_config(ctx.deps.chat_id)
        ).sticker_memory_enabled:
            return None
    except Exception as e:
        logger.warning(f"Sticker availability check failed: {e}")
        return None
    return tool_def


async def prepare_image_tools(
    ctx: RunContext[datatype.ContextDeps], tool_def: ToolDefinition
) -> ToolDefinition | None:
    """Show the image tool when either image service is available."""
    if (
        image_gen.image_gen_client is not None
        or image_gen.image_edit_client is not None
    ):
        return tool_def
    return None
