from pydantic_ai import RunContext
from pydantic_ai.tools import ToolDefinition

from kmua.plugins.agent import datatype


async def prepare_group_tools(
    ctx: RunContext[datatype.ContextDeps], tool_def: ToolDefinition
) -> ToolDefinition | None:
    """Prepare tools for group chat."""
    if ctx.deps.chat_id and ctx.deps.chat_id < -100:
        return tool_def
    return None
