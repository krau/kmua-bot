"""Layered message history compression for pydantic-ai agents.

This module implements a three-layer compression strategy that preserves
conversation structure while managing token usage:

Layer 1 (Recent):  Keep full message structure for recent messages.
Layer 2 (Middle):  Compress tool return content, keep conversation framework.
Layer 3 (Oldest):  Generate structured summary that preserves dialog flow.

Key design principles:
- Preserve ModelRequest/ModelResponse structure (don't collapse to SystemPromptPart)
- Keep tool call/return pairs intact
- Use pydantic-ai's native history_processors interface
- Token-aware dynamic compression
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic_ai import (
    Agent,
    ModelMessage,
    RunContext,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.messages import (
    MULTI_MODAL_CONTENT_TYPES,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
)

from kmua.config import app_config
from kmua.i18n import i18n
from kmua.logger import logger

# ============================================================================
# Token Estimation
# ============================================================================


@dataclass
class TokenStats:
    """Token statistics for a message list."""

    total_input: int = 0
    total_output: int = 0
    total: int = 0
    message_count: int = 0

    @classmethod
    def from_messages(cls, messages: Sequence[ModelMessage]) -> TokenStats:
        stats = cls()
        stats.message_count = len(messages)
        for msg in messages:
            if isinstance(msg, ModelResponse):
                usage = msg.usage
                stats.total_input += usage.input_tokens
                stats.total_output += usage.output_tokens
                stats.total += usage.total_tokens
        return stats


def estimate_tokens(messages: Sequence[ModelMessage]) -> int:
    """Estimate total tokens for messages using available usage data."""
    stats = TokenStats.from_messages(messages)
    if stats.total > 0:
        return stats.total
    # Fallback: rough estimation based on content length
    # ~4 chars per token for English, ~2 for CJK
    total_chars = 0
    for msg in messages:
        for part in msg.parts:
            if isinstance(part, UserPromptPart):
                content = part.content
                if isinstance(content, str):
                    total_chars += len(content)
                elif isinstance(content, list):
                    for item in content:
                        if isinstance(item, str):
                            total_chars += len(item)
            elif isinstance(part, (ToolReturnPart, RetryPromptPart)):
                content = part.content
                if isinstance(content, str):
                    total_chars += len(content)
                elif content is not None:
                    total_chars += len(str(content))
            elif isinstance(part, TextPart):
                total_chars += len(part.content)
    return total_chars // 3  # Conservative estimate


def should_compress(
    messages: Sequence[ModelMessage],
    token_window: int = 0,
    compress_ratio: float = 0.8,
    message_threshold: int = 20,
) -> tuple[bool, str]:
    """Determine if compression is needed.

    Returns:
        (should_compress, reason) tuple
    """
    if token_window > 0:
        threshold = int(token_window * compress_ratio)
        current = estimate_tokens(messages)
        if current >= threshold:
            return True, f"tokens={current} >= threshold={threshold}"
        return False, ""

    if len(messages) > message_threshold:
        return True, f"messages={len(messages)} > threshold={message_threshold}"
    return False, ""


# ============================================================================
# Message Text Extraction
# ============================================================================


def messages_to_text(messages: Sequence[ModelMessage]) -> str:
    """Convert messages to readable text format for summarization."""
    lines: list[str] = []
    for msg in messages:
        for part in msg.parts:
            match part.part_kind:
                case "system-prompt":
                    lines.append(f"[SYSTEM]: {part.content}")
                case "user-prompt":
                    if isinstance(part.content, str):
                        lines.append(f"[USER]: {part.content}")
                    else:
                        texts = [c for c in part.content if isinstance(c, str)]
                        if texts:
                            lines.append(f"[USER]: {' '.join(texts)}")
                case "text":
                    if msg.kind == "response":
                        lines.append(f"[ASSISTANT]: {part.content}")
                case "tool-call":
                    args_str = str(part.args)[:200] if part.args else ""
                    lines.append(f"[TOOL CALL]: {part.tool_name}({args_str})")
                case "tool-return":
                    content_str = str(part.content)[:300] if part.content else ""
                    lines.append(f"[TOOL RETURN {part.tool_name}]: {content_str}")
                case "retry-prompt":
                    lines.append(f"[RETRY]: {part.content}")
    return "\n".join(lines)


# ============================================================================
# Tool Call/Return Pair Validation
# ============================================================================


def validate_tool_pairs(messages: Sequence[ModelMessage]) -> bool:
    """Check if all tool calls have matching returns."""
    calls: dict[str, int] = defaultdict(int)
    returns: dict[str, int] = defaultdict(int)

    for msg in messages:
        for part in msg.parts:
            if isinstance(part, ToolCallPart):
                calls[part.tool_call_id] += 1
            elif isinstance(part, ToolReturnPart):
                returns[part.tool_call_id] += 1
            elif isinstance(part, RetryPromptPart) and part.tool_call_id:
                returns[part.tool_call_id] += 1

    for call_id, count in calls.items():
        if returns.get(call_id, 0) < count:
            return False
    return True


def find_safe_split_index(
    messages: Sequence[ModelMessage],
    target_index: int,
) -> int:
    """Find a safe index to split messages without breaking tool call/return pairs.

    If we split at target_index, any tool call whose return is at or after
    target_index must have its call also at or after target_index.

    Returns the adjusted split index that keeps all tool pairs intact.
    """
    if target_index <= 0 or target_index >= len(messages):
        return target_index

    # Map tool_call_id -> (call_msg_index, return_msg_index)
    call_positions: dict[str, int] = {}
    return_positions: dict[str, int] = {}

    for idx, msg in enumerate(messages):
        for part in msg.parts:
            if isinstance(part, ToolCallPart):
                call_positions[part.tool_call_id] = idx
            elif isinstance(part, (ToolReturnPart, RetryPromptPart)):
                if part.tool_call_id:
                    return_positions[part.tool_call_id] = idx

    # Find the minimum call index whose return is >= target_index
    min_call_for_later_return = target_index
    for call_id, return_idx in return_positions.items():
        if return_idx >= target_index and call_id in call_positions:
            call_idx = call_positions[call_id]
            min_call_for_later_return = min(min_call_for_later_return, call_idx)

    # Also ensure: if call < target_index, return must also be < target_index
    # Find the maximum return index for calls before target_index
    max_return_for_early_call = 0
    for call_id, call_idx in call_positions.items():
        if call_idx < target_index and call_id in return_positions:
            return_idx = return_positions[call_id]
            max_return_for_early_call = max(max_return_for_early_call, return_idx + 1)

    # The safe split point must be:
    # - >= max_return_for_early_call (don't split early calls from their returns)
    # - <= min_call_for_later_return (don't split late returns from their calls)
    # If these constraints conflict, prefer keeping pairs together in later layer
    safe_index = max(target_index, max_return_for_early_call)
    safe_index = min(safe_index, min_call_for_later_return)

    return safe_index


def filter_incomplete_tool_pairs(
    messages: Sequence[ModelMessage],
) -> list[ModelMessage]:
    """Remove messages with incomplete tool call/return pairs."""
    # Collect all tool call IDs and their states
    call_ids: dict[str, list[tuple[int, str]]] = defaultdict(list)

    for msg_idx, msg in enumerate(messages):
        for part in msg.parts:
            if isinstance(part, (ToolCallPart, ToolReturnPart, RetryPromptPart)):
                call_id = part.tool_call_id
                call_ids[call_id].append((msg_idx, part.part_kind))

    # Find complete pairs
    complete_call_ids: set[str] = set()
    for call_id, entries in call_ids.items():
        kinds = [e[1] for e in entries]
        has_call = "tool-call" in kinds
        has_return = "tool-return" in kinds or "retry-prompt" in kinds
        if has_call and has_return:
            complete_call_ids.add(call_id)

    # Filter messages
    result: list[ModelMessage] = []
    for msg in messages:
        has_tool_parts = any(
            isinstance(p, (ToolCallPart, ToolReturnPart, RetryPromptPart))
            for p in msg.parts
        )
        if not has_tool_parts:
            result.append(msg)
            continue

        # Include message only if all its tool parts belong to complete pairs
        msg_tool_ids = {
            p.tool_call_id
            for p in msg.parts
            if isinstance(p, (ToolCallPart, ToolReturnPart, RetryPromptPart))
        }
        if msg_tool_ids.issubset(complete_call_ids):
            result.append(msg)

    return result


# ============================================================================
# Layer 2: Tool Return Compression
# ============================================================================


def _truncate_content(content: str, max_len: int = 200) -> str:
    """Truncate content to max length with ellipsis."""
    if len(content) <= max_len:
        return content
    return content[: max_len - 3] + "...[truncated]"


def _compress_tool_return(part: ToolReturnPart) -> ToolReturnPart:
    """Compress a tool return part's content."""
    if not part.content:
        return part

    content = part.content
    if isinstance(content, str):
        compressed = _truncate_content(content)
    elif isinstance(content, MULTI_MODAL_CONTENT_TYPES):
        compressed = "[binary content removed]"
    else:
        compressed = _truncate_content(str(content))

    return ToolReturnPart(
        tool_name=part.tool_name,
        content=compressed,
        tool_call_id=part.tool_call_id,
        timestamp=part.timestamp,
    )


def compress_tool_returns(
    messages: Sequence[ModelMessage],
) -> list[ModelMessage]:
    """Compress tool return content while preserving structure."""
    result: list[ModelMessage] = []

    for msg in messages:
        if not isinstance(msg, ModelRequest):
            result.append(msg)
            continue

        new_parts = []
        changed = False
        for part in msg.parts:
            if isinstance(part, ToolReturnPart):
                compressed = _compress_tool_return(part)
                if compressed is not part:
                    changed = True
                new_parts.append(compressed)
            else:
                new_parts.append(part)

        if changed:
            result.append(ModelRequest(parts=new_parts))
        else:
            result.append(msg)

    return result


# ============================================================================
# Layer 3: Structured Summary Generation
# ============================================================================


async def _run_summary_agent(
    agent: Agent,
    messages: Sequence[ModelMessage],
    timeout: int = 0,
) -> str:
    """Run summary agent to generate conversation summary."""
    text = messages_to_text(messages)
    prompt = f"{i18n.t('bot.msg.agent.summary_prompt', locale=app_config.lang)}: {text}"

    coro = agent.run(user_prompt=prompt, message_history=[])

    if timeout > 0:
        try:
            result = await asyncio.wait_for(coro, timeout=timeout)
        except TimeoutError:
            logger.warning(f"Summary agent timed out after {timeout}s")
            raise
    else:
        result = await coro

    return result.output


def _build_summary_messages(
    summary_text: str,
    preserved_request: ModelRequest | None = None,
) -> list[ModelMessage]:
    """Build summary messages that preserve dialog structure.

    Instead of using SystemPromptPart (which loses conversation context),
    we create a ModelResponse with the summary as TextPart. This preserves
    the ModelRequest -> ModelResponse flow that pydantic-ai expects.
    """
    # Create a ModelResponse containing the summary
    # This maintains the request -> response structure
    summary_response = ModelResponse(
        parts=[TextPart(content=f"[对话摘要]: {summary_text}")],
    )

    result: list[ModelMessage] = [summary_response]

    # If there's a current user request to preserve, add it
    if preserved_request is not None:
        result.append(preserved_request)

    return result


async def summarize_with_structure(
    summary_agent: Agent,
    messages: Sequence[ModelMessage],
    timeout: int = 0,
) -> list[ModelMessage]:
    """Generate structured summary that preserves conversation flow.

    This approach:
    1. Summarizes the conversation content
    2. Preserves the ModelRequest/ModelResponse structure
    3. Keeps the current user prompt intact

    On failure, falls back to safe truncation that preserves tool pairs.
    """
    if len(messages) <= 1:
        return list(messages)

    # Separate the last message (usually current user prompt) from summarizable content
    to_summarize = messages[:-1]
    last_msg = messages[-1]

    # Generate summary
    try:
        summary_text = await _run_summary_agent(
            summary_agent, to_summarize, timeout=timeout
        )
        logger.debug(f"Generated summary: {summary_text[:200]}...")
    except Exception as e:
        logger.warning(f"Summary generation failed: {e}")
        # Fallback: safe truncation preserving tool pairs
        return _safe_fallback_truncate(messages, keep_count=6)

    # Build structured messages
    preserved_request = last_msg if isinstance(last_msg, ModelRequest) else None
    return _build_summary_messages(summary_text, preserved_request)


def _safe_fallback_truncate(
    messages: Sequence[ModelMessage],
    keep_count: int = 6,
) -> list[ModelMessage]:
    """Safely truncate messages preserving tool call/return pairs.

    Used as fallback when summarization fails.
    """
    if len(messages) <= keep_count:
        return list(messages)

    # Find safe split point
    target_index = len(messages) - keep_count
    safe_index = find_safe_split_index(messages, target_index)

    # Get messages from safe index, ensuring we keep at least a few
    result = list(messages[safe_index:])

    # If we ended up with too few messages due to pair preservation,
    # try keeping more by moving the split point earlier
    if len(result) < 3 and safe_index > 0:
        safe_index = find_safe_split_index(messages, max(0, safe_index - 3))
        result = list(messages[safe_index:])

    # Compress tool returns in result if needed
    result = compress_tool_returns(result)

    # Final validation - filter out any incomplete pairs
    result = filter_incomplete_tool_pairs(result)

    return result


# ============================================================================
# Multimodal Content Truncation
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

    # Count total multimodal items
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
                to_remove -= 1
                changed = True

        if changed:
            result[i] = ModelRequest(parts=new_parts)

    return result


# ============================================================================
# Main Compression Manager
# ============================================================================


@dataclass
class CompressionConfig:
    """Configuration for message compression."""

    # Token-based compression
    token_window: int = 0  # 0 = use message count instead
    compress_ratio: float = 0.8

    # Message count thresholds
    message_threshold: int = 20
    recent_keep_count: int = 6  # Number of recent messages to keep fully intact

    # Compression behavior
    compress_tool_returns: bool = True
    tool_return_max_length: int = 200

    # Multimodal limits
    multimodal_max_items: int = 4

    # Summary generation
    summary_timeout: int = 0  # 0 = no timeout
    use_summary: bool = True


@dataclass
class CompressionResult:
    """Result of compression operation."""

    messages: list[ModelMessage]
    was_compressed: bool
    original_count: int
    compressed_count: int
    reason: str = ""


class HistoryCompressor:
    """Manages layered message history compression.

    Implements a three-layer strategy:
    - Layer 1 (Recent): Keep full structure for recent messages
    - Layer 2 (Middle): Compress tool returns, keep dialog framework
    - Layer 3 (Oldest): Generate structured summary
    """

    def __init__(
        self,
        summary_agent: Agent | None = None,
        config: CompressionConfig | None = None,
    ):
        self.summary_agent = summary_agent
        self.config = config or CompressionConfig()

    async def compress(
        self,
        messages: Sequence[ModelMessage],
    ) -> CompressionResult:
        """Apply layered compression to messages.

        Returns CompressionResult with compressed messages and metadata.
        Always returns valid messages even if compression fails.
        """
        if not messages:
            return CompressionResult(
                messages=[],
                was_compressed=False,
                original_count=0,
                compressed_count=0,
            )

        # Check if compression is needed
        needs_compress, reason = should_compress(
            messages,
            token_window=self.config.token_window,
            compress_ratio=self.config.compress_ratio,
            message_threshold=self.config.message_threshold,
        )

        if not needs_compress:
            return CompressionResult(
                messages=list(messages),
                was_compressed=False,
                original_count=len(messages),
                compressed_count=len(messages),
                reason="no compression needed",
            )

        logger.info(f"Compressing history: {reason}")

        try:
            # Step 1: Filter incomplete tool pairs
            filtered = filter_incomplete_tool_pairs(messages)

            # Step 2: Apply layered compression
            compressed = await self._apply_layered_compression(filtered)

            # Step 3: Truncate multimodal content
            if self.config.multimodal_max_items > 0:
                compressed = truncate_multimodal(
                    compressed, self.config.multimodal_max_items
                )

            # Final safety check: ensure tool pairs are still valid
            compressed = filter_incomplete_tool_pairs(compressed)

            return CompressionResult(
                messages=compressed,
                was_compressed=True,
                original_count=len(messages),
                compressed_count=len(compressed),
                reason=reason,
            )
        except Exception as e:
            logger.error(f"Compression failed, using safe fallback: {e}")
            # Safe fallback: just truncate keeping recent messages with valid pairs
            fallback = _safe_fallback_truncate(
                messages, keep_count=self.config.recent_keep_count
            )
            return CompressionResult(
                messages=fallback,
                was_compressed=True,
                original_count=len(messages),
                compressed_count=len(fallback),
                reason=f"fallback after error: {e}",
            )

    async def _apply_layered_compression(
        self,
        messages: Sequence[ModelMessage],
    ) -> list[ModelMessage]:
        """Apply the three-layer compression strategy.

        Ensures tool call/return pairs are never split across layers.
        Uses find_safe_split_index to locate safe boundaries.
        """
        total = len(messages)
        keep = self.config.recent_keep_count

        if total <= keep:
            # No need for layered compression
            if self.config.compress_tool_returns:
                return compress_tool_returns(messages)
            return list(messages)

        # Find safe split point between Layer 1 (recent) and older messages
        raw_split = total - keep
        safe_split = find_safe_split_index(messages, raw_split)

        # If safe_split pushed us too close to the end, skip layered compression
        if total - safe_split < 3:
            if self.config.compress_tool_returns:
                return compress_tool_returns(messages)
            return list(messages)

        # Split into layers at safe boundary
        # Layer 1: Recent messages (keep intact, includes moved tool pairs)
        layer1 = messages[safe_split:]

        # Layer 2+3: Older messages
        older = messages[:safe_split]

        # Decide whether to use summary or just compress
        if (
            self.config.use_summary
            and self.summary_agent is not None
            and len(older) > 4  # Only summarize if there's enough content
        ):
            # Find safe split between summarize_part and transition_part
            # Transition should be the last 2 messages of older (if possible)
            if len(older) > 2:
                raw_transition_split = len(older) - 2
                safe_transition_split = find_safe_split_index(
                    older, raw_transition_split
                )

                # If transition split is too close to end, just use all older
                if len(older) - safe_transition_split < 2:
                    summarize_part = older
                    transition_part: list[ModelMessage] = []
                else:
                    summarize_part = older[:safe_transition_split]
                    transition_part = list(older[safe_transition_split:])

                # Generate summary from summarize_part only
                # Don't include layer1[0] as it may break pairs
                summarized = await summarize_with_structure(
                    self.summary_agent,
                    list(summarize_part),
                    timeout=self.config.summary_timeout,
                )

                # Compress tool returns in transition part
                if self.config.compress_tool_returns and transition_part:
                    transition_part = compress_tool_returns(transition_part)

                return summarized + transition_part + list(layer1)
            else:
                # Not enough older messages to warrant separate summarization
                if self.config.compress_tool_returns:
                    older_compressed = compress_tool_returns(older)
                    return older_compressed + list(layer1)
                return list(older) + list(layer1)
        else:
            # No summary agent or disabled: just compress tool returns
            if self.config.compress_tool_returns:
                older_compressed = compress_tool_returns(older)
                return older_compressed + list(layer1)
            return list(older) + list(layer1)


# ============================================================================
# History Processor (pydantic-ai compatible)
# ============================================================================


def create_history_processor(
    summary_agent: Agent | None = None,
    config: CompressionConfig | None = None,
):
    """Create a history_processor function for pydantic-ai Agent.

    Usage:
        agent = Agent(
            model=model,
            history_processors=[create_history_processor(summary_agent)],
        )
    """
    compressor = HistoryCompressor(summary_agent=summary_agent, config=config)

    async def history_processor(
        ctx: RunContext,
        messages: list[ModelMessage],
    ) -> list[ModelMessage]:
        result = await compressor.compress(messages)
        if result.was_compressed:
            logger.debug(
                f"History compressed: {result.original_count} -> "
                f"{result.compressed_count} messages ({result.reason})"
            )
        return result.messages

    return history_processor


# ============================================================================
# Legacy Compatibility Functions
# ============================================================================


def get_history_text(message_history: list[ModelMessage]) -> str:
    """Convert history to text format. Legacy compatibility."""
    return messages_to_text(message_history)


def get_history_token_count(messages: list[ModelMessage]) -> int:
    """Count tokens in history. Legacy compatibility."""
    return estimate_tokens(messages)


def should_compress_by_tokens(messages: list[ModelMessage]) -> bool:
    """Check if token-based compression is needed. Legacy compatibility."""
    result, _ = should_compress(
        messages,
        token_window=app_config.agent_context_window_tokens,
        compress_ratio=app_config.agent_context_compress_ratio,
    )
    return result


def filter_tool_return_if_needed(
    messages: list[ModelMessage],
) -> list[ModelMessage]:
    """Filter incomplete tool pairs. Legacy compatibility."""
    return filter_incomplete_tool_pairs(messages)


async def summarize_history(
    summary_agent: Agent,
    messages: list[ModelMessage],
    messages_threshold: int = app_config.agent_messages_threshold,
) -> list[ModelMessage]:
    """Summarize history with fallback. Legacy compatibility."""
    # Check if compression is needed
    needs_compress, reason = should_compress(
        messages,
        token_window=app_config.agent_context_window_tokens,
        compress_ratio=app_config.agent_context_compress_ratio,
        message_threshold=messages_threshold,
    )

    if not needs_compress:
        return messages

    logger.debug(f"Summarizing history: {reason}")

    try:
        # Use the new structured summarization
        config = CompressionConfig(
            token_window=app_config.agent_context_window_tokens,
            compress_ratio=app_config.agent_context_compress_ratio,
            message_threshold=messages_threshold,
            multimodal_max_items=app_config.agent_multimodal_max_items,
            summary_timeout=app_config.agent_model_timeout,
        )
        compressor = HistoryCompressor(summary_agent=summary_agent, config=config)
        result = await compressor.compress(messages)
        return result.messages
    except Exception as e:
        logger.exception(f"Error summarizing history: {e.__class__.__name__} - {e}")
        # Fallback: keep recent messages with tool pair filtering
        filtered = filter_incomplete_tool_pairs(messages[-messages_threshold:])
        compressed = compress_tool_returns(filtered)
        return compressed
