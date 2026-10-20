"""Search backend adapters.

Each adapter translates the unified query/result shape to one vendor API.
Adding a backend means implementing :class:`SearchProvider`, registering it
in :data:`PROVIDERS`, and exposing its settings on ``SearchConfig``.
"""

from __future__ import annotations

from typing import Any

import httpx
from ddgs import DDGS
from pydantic_ai.common_tools.duckduckgo import DuckDuckGoSearchTool

from kmua.config import SearchProviderConfig, app_config

from .base import SearchError, SearchProvider, SearchResponse, SearchResult


def _api_base(provider: SearchProvider) -> str:
    return (provider.config.url or provider.default_url).rstrip("/")


def _effective_proxy(config: SearchProviderConfig) -> str | None:
    for candidate in (config.proxy, app_config.agent_proxy):
        if candidate and candidate.strip():
            return candidate.strip()
    return None


def _client(provider: SearchProvider) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(provider.timeout, connect=min(10.0, provider.timeout)),
        proxy=_effective_proxy(provider.config),
        follow_redirects=True,
    )


def _payload(provider: SearchProvider, response: httpx.Response) -> dict[str, Any]:
    if not response.is_success:
        detail = " ".join(response.text.split())[:300]
        raise SearchError(
            f"{provider.name} returned HTTP {response.status_code}: {detail}"
        )
    try:
        data = response.json()
    except ValueError as e:
        raise SearchError(f"{provider.name} returned invalid JSON") from e
    if not isinstance(data, dict):
        raise SearchError(f"{provider.name} returned an unexpected response")
    return data


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _normalize(
    items: Any,
    *,
    title_key: str,
    url_key: str,
    snippet_keys: tuple[str, ...],
    limit: int,
) -> list[SearchResult]:
    if not isinstance(items, list):
        return []
    results: list[SearchResult] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = _text(item.get(url_key))
        if not url:
            continue
        snippet = ""
        for key in snippet_keys:
            snippet = _text(item.get(key))
            if snippet:
                break
        results.append(
            SearchResult(
                title=_text(item.get(title_key)) or url,
                url=url,
                snippet=snippet,
            )
        )
        if len(results) >= limit:
            break
    return results


class TavilySearch(SearchProvider):
    name = "tavily"
    default_url = "https://api.tavily.com"

    def availability_error(self) -> str | None:
        if not self.config.key.strip():
            return "missing API key (agent_search.tavily.key)"
        return None

    async def search(self, query: str, max_results: int) -> SearchResponse:
        limit = min(max_results, 20)
        async with _client(self) as client:
            response = await client.post(
                f"{_api_base(self)}/search",
                headers={"Authorization": f"Bearer {self.config.key.strip()}"},
                json={
                    "query": query,
                    "max_results": limit,
                    "search_depth": "basic",
                    "include_answer": (
                        "basic" if self.config.include_answer else False
                    ),
                },
            )
        data = _payload(self, response)
        results = _normalize(
            data.get("results"),
            title_key="title",
            url_key="url",
            snippet_keys=("content",),
            limit=limit,
        )
        answer = (
            _text(data.get("answer") or "") or None
            if self.config.include_answer
            else None
        )
        return SearchResponse(results=results, answer=answer)


class BraveSearch(SearchProvider):
    name = "brave"
    default_url = "https://api.search.brave.com"

    def availability_error(self) -> str | None:
        if not self.config.key.strip():
            return "missing API key (agent_search.brave.key)"
        return None

    async def search(self, query: str, max_results: int) -> SearchResponse:
        limit = min(max_results, 20)
        async with _client(self) as client:
            response = await client.get(
                f"{_api_base(self)}/res/v1/web/search",
                headers={
                    "X-Subscription-Token": self.config.key.strip(),
                    "Accept": "application/json",
                },
                params={"q": query, "count": limit},
            )
        data = _payload(self, response)
        web = data.get("web")
        items = web.get("results") if isinstance(web, dict) else None
        results = _normalize(
            items,
            title_key="title",
            url_key="url",
            snippet_keys=("description",),
            limit=limit,
        )
        return SearchResponse(results=results)


class DeepSeekSearch(SearchProvider):
    name = "deepseek"
    default_url = "https://api.deepseek.com"

    def availability_error(self) -> str | None:
        if not self.config.key.strip():
            return "missing API key (agent_search.deepseek.key)"
        return None

    async def search(self, query: str, max_results: int) -> SearchResponse:
        # The API caps the query at 128 Unicode characters.
        limit = min(max_results, 50)
        async with _client(self) as client:
            response = await client.post(
                f"{_api_base(self)}/v1/tools/search",
                headers={"Authorization": f"Bearer {self.config.key.strip()}"},
                json={
                    "query": query[:128],
                    "count": limit,
                    "need_content": False,
                },
            )
        data = _payload(self, response)
        results = _normalize(
            data.get("results"),
            title_key="title",
            url_key="url",
            snippet_keys=("snippet", "summary"),
            limit=limit,
        )
        return SearchResponse(results=results)


class DuckDuckGoSearch(SearchProvider):
    """Free, keyless fallback backend."""

    name = "duckduckgo"
    default_url = "https://duckduckgo.com"

    async def search(self, query: str, max_results: int) -> SearchResponse:
        limit = min(max_results, 10)
        results = await DuckDuckGoSearchTool(DDGS(), max_results=limit).__call__(query)
        return SearchResponse(
            results=[
                SearchResult(
                    title=result.get("title") or result.get("href", ""),
                    url=result.get("href", ""),
                    snippet=result.get("body", ""),
                )
                for result in results
            ]
        )


PROVIDERS: dict[str, type[SearchProvider]] = {
    provider.name: provider
    for provider in (
        TavilySearch,
        BraveSearch,
        DeepSeekSearch,
        DuckDuckGoSearch,
    )
}
