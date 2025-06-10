from pydantic_ai import RunContext
from pydantic_ai.tools import ToolDefinition

from kmua.config import app_config
from kmua.plugins.agent import datatype


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
    """Prepare tools for configurable chat."""
    if tool_def.name in app_config.agent_extra_tools:
        return tool_def
    return None
