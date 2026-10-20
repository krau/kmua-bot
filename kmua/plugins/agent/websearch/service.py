"""Priority-ordered web search with fallback across enabled backends."""

from __future__ import annotations

from kmua.config import SearchConfig, SearchProviderConfig, app_config
from kmua.logger import logger

from .base import SearchError, SearchProvider, SearchResponse
from .providers import PROVIDERS


class SearchService:
    """Try enabled providers in order until one returns a usable response.

    A provider is skipped when it is unconfigured (for example a paid backend
    without an API key), and failures fall through to the next provider.
    A response counts as usable when it has hits or a query-level answer.
    Empty responses fall through only when ``fallback_on_empty`` is set.
    """

    def __init__(
        self,
        providers: list[SearchProvider],
        *,
        fallback_on_empty: bool = True,
    ) -> None:
        self.providers = providers
        self.fallback_on_empty = fallback_on_empty

    @classmethod
    def from_config(cls, config: SearchConfig | None = None) -> SearchService:
        config = config or app_config.agent_search
        providers: list[SearchProvider] = []
        seen: set[str] = set()
        for raw_name in config.providers:
            name = raw_name.strip().lower()
            if not name or name in seen:
                continue
            seen.add(name)
            provider_type = PROVIDERS.get(name)
            if provider_type is None:
                logger.warning(
                    f"Unknown web search provider {name!r} in "
                    f"agent_search.providers; available: {', '.join(PROVIDERS)}"
                )
                continue
            provider_config = getattr(config, name, None)
            if not isinstance(provider_config, SearchProviderConfig):
                provider_config = SearchProviderConfig()
            providers.append(provider_type(provider_config, config.timeout))
        return cls(providers, fallback_on_empty=config.fallback_on_empty)

    async def search(self, query: str, max_results: int) -> SearchResponse:
        if not self.providers:
            raise SearchError(
                "No web search providers are configured; set agent_search.providers"
            )

        errors: list[str] = []
        completed = False
        for provider in self.providers:
            reason = provider.availability_error()
            if reason:
                logger.debug(f"Web search provider {provider.name} skipped: {reason}")
                errors.append(f"{provider.name}: {reason}")
                continue
            try:
                response = await provider.search(query, max_results)
            except Exception as e:
                logger.warning(
                    f"Web search provider {provider.name} failed: "
                    f"{e.__class__.__name__}: {e}"
                )
                errors.append(f"{provider.name}: {e}")
                continue
            completed = True
            if response.results or response.answer:
                return SearchResponse(
                    results=response.results[:max_results],
                    answer=response.answer,
                )
            logger.debug(f"Web search provider {provider.name} returned no results")
            if not self.fallback_on_empty:
                return SearchResponse()

        # Some providers ran successfully but all returned empty responses.
        if completed:
            return SearchResponse()
        raise SearchError("All web search providers failed: " + "; ".join(errors))


async def search_web(query: str, max_results: int) -> SearchResponse:
    """Search the web using the configured provider priority."""
    return await SearchService.from_config().search(query, max_results)


__all__ = ["SearchError", "SearchResponse", "SearchService", "search_web"]
