"""Counting what the group-memory backend spends on the model.

powermem reads its own LLM configuration - provider, model, credentials - out of the
document it is handed, so nothing in the agent sees its calls or their cost. Its
providers do call a `response_callback` after every request, and the raw provider
response still carries the token usage there, so `install` puts that hook into the
config and `collect` gathers the calls of one operation. The caller then settles them
like any other run.

The collector is a context variable rather than an attribute on the memory instance:
several chats update their memory concurrently, and each has to end up charged for
its own calls.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from pydantic_ai.usage import RunUsage

# The calls of the operation currently running, or None outside one.
_calls: ContextVar[list[tuple[int, int]] | None] = ContextVar(
    "kmua_powermem_usage", default=None
)


def install(config: dict[str, Any] | None) -> dict[str, Any] | None:
    """The given powermem config with the usage hook added, for `AsyncMemory`.

    A copy: the config object is the deployment's, and its other readers should not
    suddenly hold a callable they cannot serialize.
    """
    if config is None:
        return None
    installed = dict(config)
    llm = dict(installed.get("llm") or {})
    settings = dict(llm.get("config") or {})
    settings["response_callback"] = _record
    llm["config"] = settings
    installed["llm"] = llm
    return installed


def _record(_llm: Any, response: Any, _params: Any) -> None:
    """Remember one provider call's tokens; powermem calls this after each request."""
    calls = _calls.get()
    if calls is None:
        return
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    calls.append(
        (
            int(getattr(usage, "prompt_tokens", 0) or 0),
            int(getattr(usage, "completion_tokens", 0) or 0),
        )
    )


@contextmanager
def collect() -> Iterator[list[tuple[int, int]]]:
    """Gather the token usage of every model call made inside the block."""
    calls: list[tuple[int, int]] = []
    token = _calls.set(calls)
    try:
        yield calls
    finally:
        _calls.reset(token)


def usage_of(calls: list[tuple[int, int]]) -> RunUsage | None:
    """The calls as one run usage, or None when nothing was recorded."""
    if not calls:
        return None
    return RunUsage(
        input_tokens=sum(prompt for prompt, _ in calls),
        output_tokens=sum(completion for _, completion in calls),
    )


__all__ = ["collect", "install", "usage_of"]
