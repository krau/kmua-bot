"""Unified web search backends used by the agent's ``web://`` tool."""

from .base import SearchError, SearchResponse, SearchResult
from .service import SearchService, search_web

__all__ = [
    "SearchError",
    "SearchResponse",
    "SearchResult",
    "SearchService",
    "search_web",
]
