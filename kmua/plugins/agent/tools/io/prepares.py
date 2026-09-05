"""Per-tool visibility: mirror protocol availability into tool descriptions."""

from __future__ import annotations

from pydantic_ai import RunContext
from pydantic_ai.tools import ToolDefinition

from kmua.config import app_config

from .. import datatype
from .protocols import (
    _PROTOCOLS,
    _is_group_chat,
    _kmua_enabled,
    _memory_enabled,
    _sandbox_enabled,
    _web_fetch_enabled,
    _web_search_enabled,
)


def _trim_unavailable_protocols(
    tool_def: ToolDefinition,
    protocols: dict[str, bool],
    known: tuple[str, ...] = (*_PROTOCOLS, "http"),
) -> ToolDefinition | None:
    """Trim description lines whose protocols are unavailable; hide the tool
    when none of the tool's own protocols is usable.

    ``protocols`` drives hiding (empty/False-everywhere => None); a line is
    dropped when it mentions any known protocol that is not in ``protocols``
    with True. Lines without a known protocol prefix (usage notes) stay.
    """
    if not any(protocols.values()):
        return None
    if tool_def.description:
        lines = []
        for ln in tool_def.description.splitlines():
            if any(p in ln for p in known):
                if not any(p in ln and protocols.get(p) for p in known):
                    continue
            lines.append(ln)
        trimmed = "\n".join(lines).strip()
        if trimmed != tool_def.description.strip():
            tool_def.description = trimmed
    return tool_def


async def prepare_read(
    ctx: RunContext[datatype.ContextDeps], tool_def: ToolDefinition
) -> ToolDefinition | None:
    """Show read with the protocols currently readable."""
    return _trim_unavailable_protocols(
        tool_def,
        {
            "kmua://": _kmua_enabled(),
            "work://": bool(app_config.agent_workspace_enabled),
            "persist://": True,
            "chat://": _is_group_chat(ctx.deps),
            "http": _web_fetch_enabled(),
        },
    )


async def prepare_write(
    ctx: RunContext[datatype.ContextDeps], tool_def: ToolDefinition
) -> ToolDefinition | None:
    """Show write with the protocols currently writable."""
    return _trim_unavailable_protocols(
        tool_def,
        {
            "work://": bool(app_config.agent_workspace_enabled),
            "persist://": True,
            "memory://": await _memory_enabled(ctx),
        },
    )


async def prepare_edit(
    ctx: RunContext[datatype.ContextDeps], tool_def: ToolDefinition
) -> ToolDefinition | None:
    """Show edit only when the workspace (its sole protocol) is enabled."""
    if not app_config.agent_workspace_enabled:
        return None
    return tool_def


async def prepare_list(
    ctx: RunContext[datatype.ContextDeps], tool_def: ToolDefinition
) -> ToolDefinition | None:
    """Show list with the protocols currently listable."""
    return _trim_unavailable_protocols(
        tool_def,
        {
            "work://": bool(app_config.agent_workspace_enabled),
            "persist://": True,
            "kmua://": _kmua_enabled(),
            "sandbox://": await _sandbox_enabled(ctx),
        },
    )


async def prepare_search(
    ctx: RunContext[datatype.ContextDeps], tool_def: ToolDefinition
) -> ToolDefinition | None:
    """Show search with the protocols currently searchable."""
    return _trim_unavailable_protocols(
        tool_def,
        {
            "kmua://": _kmua_enabled(),
            "work://": bool(app_config.agent_workspace_enabled),
            "web://": _web_search_enabled(),
            "chat://": _is_group_chat(ctx.deps),
            "memory://": await _memory_enabled(ctx),
        },
    )


async def prepare_delete(
    ctx: RunContext[datatype.ContextDeps], tool_def: ToolDefinition
) -> ToolDefinition | None:
    """Show delete with the protocols currently deletable."""
    return _trim_unavailable_protocols(
        tool_def,
        {
            "work://": bool(app_config.agent_workspace_enabled),
            "persist://": True,
            "sandbox://": await _sandbox_enabled(ctx),
        },
    )


__all__ = [
    "prepare_read",
    "prepare_write",
    "prepare_edit",
    "prepare_list",
    "prepare_search",
    "prepare_delete",
]
