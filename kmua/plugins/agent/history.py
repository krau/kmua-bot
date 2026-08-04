"""Conversation-history compaction for the agent.

Compaction is delegated to pydantic-ai-harness's ``TieredCompaction``:
cheap zero-LLM passes first (clear old tool results), an LLM summary last,
escalating only while the history exceeds ``agent_compaction_target_tokens``.
The summary model inherits the run's model (the summary agent's).

kmua-specific invariants kept on top of the harness:
- The pair-complete prefix before the last deferred (unresolved) tool call is
  the only part compaction may touch; the deferred call and everything after
  it survive verbatim, so a pending ask_user answer can still resolve.
- Multimodal content is trimmed to ``agent_multimodal_max_items`` after
  compaction (the harness counts binary parts as zero tokens and never
  touches them).
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic_ai import Agent, ModelMessage
from pydantic_ai.messages import (
    MULTI_MODAL_CONTENT_TYPES,
    ModelRequest,
    RetryPromptPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings
from pydantic_ai_harness.compaction import (
    ClearToolResults,
    SummarizingCompaction,
    TieredCompaction,
    compact_now,
)

from kmua.config import app_config
from kmua.logger import logger

# ============================================================================
# Deferred tool calls
# ============================================================================


def find_deferred_tool_call_index(
    messages: Sequence[ModelMessage],
) -> int | None:
    """Find the index of the last message containing an unresolved (deferred) tool call.

    A tool call is deferred if it has no corresponding tool-return or retry-prompt.
    Returns the message index, or None if all tool calls are resolved.
    """
    call_positions: dict[str, int] = {}
    resolved_call_ids: set[str] = set()

    for idx, msg in enumerate(messages):
        for part in msg.parts:
            if isinstance(part, ToolCallPart):
                call_positions[part.tool_call_id] = idx
            elif isinstance(part, (ToolReturnPart, RetryPromptPart)):
                if part.tool_call_id:
                    resolved_call_ids.add(part.tool_call_id)

    deferred_indices = [
        idx
        for call_id, idx in call_positions.items()
        if call_id not in resolved_call_ids
    ]
    if not deferred_indices:
        return None
    return max(deferred_indices)


# ============================================================================
# Multimodal trimming
# ============================================================================


def truncate_multimodal(
    messages: Sequence[ModelMessage],
    max_items: int,
) -> list[ModelMessage]:
    """Limit multimodal content items across all messages.

    Removes oldest multimodal items first while preserving text content.
    """
    if max_items <= 0:
        return list(messages)

    total = 0
    for msg in messages:
        if not isinstance(msg, ModelRequest):
            continue
        for part in msg.parts:
            if isinstance(part, UserPromptPart) and isinstance(part.content, list):
                total += sum(
                    1
                    for item in part.content
                    if isinstance(item, MULTI_MODAL_CONTENT_TYPES)
                )
            elif isinstance(part, ToolReturnPart) and isinstance(
                part.content, MULTI_MODAL_CONTENT_TYPES
            ):
                total += 1

    to_remove = total - max_items
    if to_remove <= 0:
        return list(messages)

    result: list[ModelMessage] = list(messages)
    for i, msg in enumerate(result):
        if to_remove <= 0:
            break
        if not isinstance(msg, ModelRequest):
            continue

        new_parts = list(msg.parts)
        changed = False

        for j, part in enumerate(new_parts):
            if to_remove <= 0:
                break

            if isinstance(part, UserPromptPart) and isinstance(part.content, list):
                new_content = []
                for item in part.content:
                    if to_remove > 0 and isinstance(item, MULTI_MODAL_CONTENT_TYPES):
                        new_content.append("[multimodal content removed]")
                        to_remove -= 1
                    else:
                        new_content.append(item)
                new_parts[j] = UserPromptPart(
                    content=new_content, timestamp=part.timestamp
                )
                changed = True
            elif isinstance(part, ToolReturnPart) and isinstance(
                part.content, MULTI_MODAL_CONTENT_TYPES
            ):
                new_parts[j] = ToolReturnPart(
                    tool_name=part.tool_name,
                    content="[multimodal content removed]",
                    tool_call_id=part.tool_call_id,
                    timestamp=part.timestamp,
                )
                changed = True
                to_remove -= 1

        if changed:
            result[i] = ModelRequest(parts=new_parts)

    return result


# ============================================================================
# Compaction (pydantic-ai-harness)
# ============================================================================


@dataclass
class InPlaceSummarizingCompaction(SummarizingCompaction):
    """SummarizingCompaction whose summary call reuses the run's own context.

    The harness's ``_summarize`` renders the history into a text prompt and
    calls a fresh ``Agent`` with a hardcoded generic instruction, so the
    summary request shares no prompt-cache prefix with the conversation.
    This subclass instead runs the summary through the main agent itself:
    the request is built by the agent's own graph from the same system prompt
    (``ctx.deps.instructions``), the same tool schemas, and the verbatim
    message history - byte-identical to the conversation's cached prefix -
    plus the summary instruction (``agent_compaction_summary_instruction``,
    the one customizable part; the model is always the conversation's own).
    ``tool_choice='none'`` keeps the tool schemas in the request (cache
    alignment) while making tool execution impossible. All other mechanisms
    (incremental anchoring, safe cutoffs, keep_user_messages, receipts,
    pinning) are inherited unchanged.
    """

    agent: Any = None
    """The main agent instance; its summary run reproduces the conversation's
    request shape exactly."""

    async def _summarize(
        self,
        messages: list[ModelMessage],
        ctx,
        *,
        previous_summary: str | None = None,
    ) -> str:
        if self.agent is None:
            raise RuntimeError("InPlaceSummarizingCompaction requires the main agent")
        instruction = app_config.agent_compaction_summary_instruction
        if previous_summary is not None:
            instruction = (
                f"{instruction}\n\n"
                "Update the previous summary in place: preserve still-true "
                "details, remove stale ones, and merge in new facts.\n\n"
                f"<previous-summary>\n{previous_summary}\n</previous-summary>"
            )
        async with self.agent.iter(
            user_prompt=instruction,
            message_history=list(messages),
            deps=ctx.deps,
            model=ctx.model,
            model_settings=ModelSettings(tool_choice="none"),
            usage=ctx.usage,
        ) as agent_run:
            async for node in agent_run:
                if Agent.is_end_node(node):
                    output = agent_run.result.output
                    return output.strip() if isinstance(output, str) else ""
        return ""


def build_compaction_strategy(agent: Any | None = None) -> TieredCompaction | None:
    """Build the conversation-compaction strategy from config.

    Cheap zero-LLM tiers first (clear old tool results), LLM summarization
    last, escalating only while the history exceeds the compression threshold
    (``agent_context_window_tokens`` x ``agent_context_compress_ratio``).
    The summarize tier needs the main agent (its summary run reproduces the
    conversation's request shape for prompt-cache hits); without it the tier
    is skipped. Returns None when compaction is disabled (window <= 0) or
    every tier is disabled.
    """
    window = app_config.agent_context_window_tokens
    if window <= 0:
        return None
    target = max(1, int(window * app_config.agent_context_compress_ratio))
    tiers: list[object] = []
    if app_config.agent_compaction_clear_tool_results:
        tiers.append(
            ClearToolResults(
                max_tokens=1,  # trigger bypassed inside TieredCompaction
                keep_pairs=app_config.agent_compaction_keep_pairs,
            )
        )
    if app_config.agent_compaction_summarize:
        if agent is None:
            logger.warning(
                "compaction: summarize tier skipped (no main agent available)"
            )
        else:
            tiers.append(
                InPlaceSummarizingCompaction(
                    agent=agent,
                    model=None,  # inherits the run model (ctx.model)
                    max_messages=1,  # trigger bypassed inside TieredCompaction
                    keep_messages=app_config.agent_compaction_keep_messages,
                )
            )
    if not tiers:
        return None
    return TieredCompaction(
        tiers=tiers,  # type: ignore[arg-type]
        target_tokens=target,
    )


# Serializes compaction across chats and prevents recursion when the summary
# run's ProcessHistory re-enters compact_history.
_compaction_lock = asyncio.Lock()


async def compact_history(
    messages: list[ModelMessage],
    model: Model | None,
    deps: object | None = None,
    agent: Any | None = None,
) -> list[ModelMessage]:
    """Compact a conversation history with the configured strategy.

    Only the pair-complete prefix before the last deferred (unresolved) tool
    call is compacted; the deferred call and everything after it survive
    verbatim, so a pending ask_user answer can still resolve. Multimodal
    content is trimmed after compaction. ``model`` is the run's model, ``deps``
    carries the run's instructions (the summary run reuses them as its system
    prompt), and ``agent`` is the main agent whose request shape the summary
    run reproduces for prompt-cache hits. Returns the (possibly unchanged)
    history.
    """
    if not messages:
        return []
    if _compaction_lock.locked():
        # A compaction (possibly our own summary run) is in progress: skip so
        # cross-chat compactions never serialize and the summary run's
        # ProcessHistory cannot recurse.
        return list(messages)
    strategy = build_compaction_strategy(agent)
    if strategy is None:
        return list(messages)
    if model is None:
        return list(messages)

    deferred_idx = find_deferred_tool_call_index(messages)
    prefix = messages if deferred_idx is None else messages[:deferred_idx]
    tail: list[ModelMessage] = [] if deferred_idx is None else messages[deferred_idx:]
    if not prefix:
        return list(messages)

    async with _compaction_lock:
        try:
            compacted = await compact_now(
                strategy, list(prefix), model=model, deps=deps
            )
        except Exception as e:
            logger.error(f"compact_history failed: {e.__class__.__name__} - {e}")
            return list(messages)

    result: list[ModelMessage] = compacted + tail
    if app_config.agent_multimodal_max_items > 0:
        result = truncate_multimodal(result, app_config.agent_multimodal_max_items)
    return result


__all__ = [
    "build_compaction_strategy",
    "compact_history",
    "find_deferred_tool_call_index",
    "truncate_multimodal",
]
