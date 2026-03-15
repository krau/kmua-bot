from pydantic_ai import RunContext
from pydantic_ai.tools import ToolDefinition

from kmua import common
from kmua.config import app_config
from kmua.logger import logger
from kmua.plugins.agent import datatype, state, sticker_memory, sticker_vec
from kmua.services import btts, image_gen


async def prepare_group_tools(
    ctx: RunContext[datatype.ContextDeps], tool_def: ToolDefinition
) -> ToolDefinition | None:
    """Prepare tools for group chat."""
    if ctx.deps.chat_id and ctx.deps.chat_id < -100:
        return tool_def
    return None


async def prepare_configurable_tools(
    ctx: RunContext[datatype.ContextDeps], tool_def: ToolDefinition
) -> ToolDefinition | None:
    if tool_def.name in app_config.agent_extra_tools:
        return tool_def
    return None


async def prepare_message_search_tool(
    ctx: RunContext[datatype.ContextDeps], tool_def: ToolDefinition
) -> ToolDefinition | None:
    if not btts.btts_client:
        return None
    if not ctx.deps.chat_id or not ctx.deps.chat_id < -100:
        return None
    indexed = await common.memttlcache.get("agent:tools:search:btts_indexed", None)
    current_chat = str(ctx.deps.chat_id).removeprefix("-100")
    if indexed is not None and isinstance(indexed, list):
        chat_ids = [str(chat_id).removeprefix("-100") for chat_id in indexed]
        if current_chat in chat_ids:
            return tool_def
        return None
    chat_ids, err = await btts.btts_client.indexed()
    if err:
        logger.error(f"Failed to fetch indexed chats: {err}")
        return None
    await common.memttlcache.set(
        "agent:tools:search:btts_indexed", chat_ids, app_config.btts_indexed_cachettl
    )
    current_chat = str(ctx.deps.chat_id).removeprefix("-100")
    chat_ids = [str(chat_id).removeprefix("-100") for chat_id in chat_ids]
    if current_chat in chat_ids:
        return tool_def
    return None


async def prepare_powermem_tool(
    ctx: RunContext[datatype.ContextDeps], tool_def: ToolDefinition
) -> ToolDefinition | None:
    if (
        app_config.agent_powermem_config is not None
        and ctx.deps.powermemory is not None
        and ctx.deps.chat_id < -100  # current powermem tool is only for group chat
    ):
        return tool_def
    return None


async def prepare_image_gen_tools(
    ctx: RunContext[datatype.ContextDeps], tool_def: ToolDefinition
) -> ToolDefinition | None:
    if image_gen.image_gen_client is not None:
        return tool_def
    return None


async def prepare_image_edit_tools(
    ctx: RunContext[datatype.ContextDeps], tool_def: ToolDefinition
) -> ToolDefinition | None:
    if image_gen.image_edit_client is not None:
        return tool_def
    return None


async def prepare_periodic_sticker(
    ctx: RunContext[datatype.ContextDeps], tool_def: ToolDefinition
) -> ToolDefinition | None:
    """Show send_sticker only when sticker memory has enough stickers (>=20) for the chat."""
    if not app_config.agent_sticker_memory:
        return None
    if sticker_memory.embedder is None:
        return None
    if ctx.deps.chat_id is None or ctx.deps.chat_id >= -100:
        return None

    # Check if the chat has enough stickers stored (minimum 20)
    MIN_STICKER_COUNT = 20
    try:
        sticker_count = await sticker_vec.count(ctx.deps.chat_id)
        if sticker_count < MIN_STICKER_COUNT:
            return None
    except Exception as e:
        logger.warning(
            f"Failed to check sticker count for chat {ctx.deps.chat_id}: {e}"
        )
        return None

    interval = app_config.agent_periodic_sticker_interval
    if interval <= 0:
        return tool_def
    counter: int = await common.memstore.get(
        state.periodic_sticker_counter_key(ctx.deps.chat_id, ctx.deps.user_id), 0
    )
    if (
        counter % interval == 0
        and counter > 0
        and "send_sticker" not in ctx.deps.tools_called_this_turn
    ):
        tool_def.description = (
            (tool_def.description or "")
            + "\n\n**YOU MUST call this tool exactly once in this turn.** "
            "Pick the query that best fits the current mood or topic."
        )
    return tool_def


async def prepare_periodic_reaction(
    ctx: RunContext[datatype.ContextDeps], tool_def: ToolDefinition
) -> ToolDefinition | None:
    """Show send_reaction always; force-call hint on threshold turns."""
    interval = app_config.agent_periodic_reaction_interval
    if interval <= 0:
        return tool_def
    counter: int = await common.memstore.get(
        state.periodic_reaction_counter_key(ctx.deps.chat_id, ctx.deps.user_id), 0
    )
    if (
        counter % interval == 0
        and counter > 0
        and "send_reaction" not in ctx.deps.tools_called_this_turn
    ):
        tool_def.description = (
            (tool_def.description or "")
            + "\n\n**YOU MUST call this tool exactly once in this turn.** "
            "Choose an emoji that reflects your genuine reaction to the user's message."
        )
    return tool_def


async def prepare_code_awareness_tools(
    ctx: RunContext[datatype.ContextDeps], tool_def: ToolDefinition
) -> ToolDefinition | None:
    """Show code awareness tools only when enabled in config."""
    if app_config.agent_code_awareness:
        return tool_def
    return None
