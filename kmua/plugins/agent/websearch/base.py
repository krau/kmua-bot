"""Provider contracts for the agent's web search backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar

from kmua.config import SearchProviderConfig


@dataclass(frozen=True, slots=True)
class SearchResult:
    """A provider-independent single search hit."""

    title: str
    url: str
    snippet: str = ""


@dataclass(frozen=True, slots=True)
class SearchResponse:
    """Everything one backend returned for a query.

    ``answer`` carries a query-level synthesized answer (Tavily's
    ``include_answer``); ``results`` holds the individual hits. Backends that
    only return hits leave ``answer`` as None.
    """

    results: list[SearchResult] = field(default_factory=list)
    answer: str | None = None


class SearchError(RuntimeError):
    """A search backend failed or is unusable."""


class SearchProvider(ABC):
    """One search backend behind the unified ``search`` call."""

    name: ClassVar[str]
    default_url: ClassVar[str]

    def __init__(self, config: SearchProviderConfig, timeout: float) -> None:
        self.config = config
        self.timeout = timeout

    def availability_error(self) -> str | None:
        """Return why the backend cannot serve requests, or None."""
        return None

    @abstractmethod
    async def search(self, query: str, max_results: int) -> SearchResponse:
        """Run one web search and return normalized results and answer."""
