from pydantic_ai import RunContext
from pydantic_ai.tools import ToolDefinition

from kmua import common
from kmua.config import app_config
from kmua.logger import logger
from kmua.plugins.agent import datatype
from kmua.services import btts


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
