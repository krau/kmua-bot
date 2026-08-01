"""Prompt-cache hit statistics for OpenAI-compatible chat models.

Records cache hit/miss token counts for every model request (streamed and
non-streamed) without provider-specific code: the extraction reads the two
usage shapes that are de-facto standard across OpenAI-compatible endpoints
(OpenAI's nested ``prompt_tokens_details`` and the flat ``prompt_cache_*_tokens``
fields used by DeepSeek and compatible gateways), falling back to pydantic-ai's
own usage parsing.
"""

from dataclasses import dataclass, field
from typing import Any

from openai.types.chat.chat_completion_chunk import ChatCompletionChunk
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models.openai import OpenAIStreamedResponse
from pydantic_ai.usage import RequestUsage, UsageBase

from kmua.logger import logger


def extract_cache_stats(raw_usage: Any) -> tuple[int, int] | None:
    """Extract (cache_read_tokens, cache_write_tokens) from a raw usage payload.

    Handles the two shapes used by OpenAI-compatible APIs:
    - nested: ``usage.prompt_tokens_details.{cached_tokens, cache_write_tokens}``
    - flat:   ``usage.{prompt_cache_hit_tokens, prompt_cache_miss_tokens}``

    Returns None when the payload carries no cache fields.
    """
    if raw_usage is None:
        return None
    read = 0
    write = 0
    prompt_details = getattr(raw_usage, "prompt_tokens_details", None)
    if prompt_details is not None:
        read = getattr(prompt_details, "cached_tokens", None) or 0
        write = getattr(prompt_details, "cache_write_tokens", None) or 0
    read = read or getattr(raw_usage, "prompt_cache_hit_tokens", None) or 0
    write = write or getattr(raw_usage, "prompt_cache_miss_tokens", None) or 0
    if not read and not write:
        return None
    return read, write


def cache_stats_from_usage(usage: UsageBase | None) -> tuple[int, int, int]:
    """Normalize (input_tokens, cache_read_tokens, cache_write_tokens).

    Reads pydantic-ai's extracted cache fields plus vendor-specific extras that
    land in ``usage.details`` (e.g. DeepSeek's ``prompt_cache_hit_tokens``).
    """
    if usage is None:
        return 0, 0, 0
    read = usage.cache_read_tokens or usage.details.get("prompt_cache_hit_tokens", 0)
    write = usage.cache_write_tokens or usage.details.get("prompt_cache_miss_tokens", 0)
    return usage.input_tokens, read, write


def log_cache_stats(model_name: str, raw_usage: Any, usage: UsageBase | None) -> None:
    """Log prompt-cache hit stats for a single model request (debug level).

    ``raw_usage`` is the provider payload (may carry cache fields pydantic-ai's
    parser missed for unknown gateways); ``usage`` is pydantic-ai's parsed usage.
    """
    input_tokens, read, write = cache_stats_from_usage(usage)
    if raw_stats := extract_cache_stats(raw_usage):
        raw_read, raw_write = raw_stats
        read = read or raw_read
        write = write or raw_write
        raw_input = getattr(raw_usage, "prompt_tokens", 0) or 0
        input_tokens = input_tokens or raw_input
    if input_tokens <= 0:
        return
    hit_rate = read / input_tokens
    logger.debug(
        f"prompt cache: model={model_name} input={input_tokens} "
        f"cached={read} ({hit_rate:.1%}) cache_write={write}"
    )


def log_run_cache_stats(model_name: str, usage: UsageBase | None) -> None:
    """Log a per-run prompt-cache hit summary (info level)."""
    if usage is None:
        return
    input_tokens, read, write = cache_stats_from_usage(usage)
    if input_tokens <= 0:
        return
    hit_rate = read / input_tokens
    requests = getattr(usage, "requests", 0)
    logger.info(
        f"prompt cache summary: model={model_name} requests={requests} "
        f"input={input_tokens} cached={read} ({hit_rate:.1%}) cache_write={write}"
    )


@dataclass(repr=False)
class CacheStatsOpenAIStreamedResponse(OpenAIStreamedResponse):
    """Streamed response that records prompt-cache stats once fully consumed."""

    _last_raw_usage: Any = field(default=None, init=False, repr=False)

    def _map_usage(self, response: ChatCompletionChunk) -> RequestUsage:
        # Keep the last chunk's raw usage: OpenAI-compatible endpoints send the
        # full usage on the final (choices-less) chunk.
        self._last_raw_usage = response.usage
        return super()._map_usage(response)

    def get(self) -> ModelResponse:
        response = super().get()
        log_cache_stats(self._model_name, self._last_raw_usage, self._usage)
        return response
