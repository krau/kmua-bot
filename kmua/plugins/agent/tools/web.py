from dataclasses import dataclass
from typing import Any, cast

import aiohttp
from crawl4ai import AsyncWebCrawler, CacheMode, CrawlerRunConfig, HTTPCrawlerConfig
from crawl4ai.async_crawler_strategy import AsyncHTTPCrawlerStrategy
from crawl4ai.models import CrawlResult, StringCompatibleMarkdown
from pydantic_ai import ModelRetry, RunContext

from kmua.config import app_config
from kmua.logger import logger

from .. import datatype

MAX_CONTENT_LENGTH = 8000

_http_strategy = AsyncHTTPCrawlerStrategy(
    browser_config=HTTPCrawlerConfig(method="GET", verify_ssl=False)
)

_run_config = CrawlerRunConfig(
    cache_mode=CacheMode.BYPASS,
    word_count_threshold=10,
    excluded_tags=["nav", "footer", "aside", "script", "style"],
    exclude_external_images=True,
)


@dataclass
class WebFetchResult:
    success: bool
    url: str
    content: str | None = None
    error: str | None = None


def _truncate(text: str) -> str:
    if len(text) > MAX_CONTENT_LENGTH:
        return (
            text[:MAX_CONTENT_LENGTH]
            + f"\n\n[Content truncated at {MAX_CONTENT_LENGTH} characters]"
        )
    return text


async def _fetch_http(url: str) -> WebFetchResult:
    async with AsyncWebCrawler(crawler_strategy=_http_strategy) as crawler:
        raw = await crawler.arun(url, config=_run_config)
    result = cast(CrawlResult, raw)
    if not result.success:
        return WebFetchResult(
            success=False,
            url=url,
            error=result.error_message or "Fetch failed",
        )
    md = result.markdown
    text: str
    if isinstance(md, StringCompatibleMarkdown):
        text = md.raw_markdown
    else:
        text = str(md) if md else ""
    if not text.strip():
        return WebFetchResult(
            success=False,
            url=url,
            error="Page returned empty content",
        )
    return WebFetchResult(success=True, url=url, content=_truncate(text))


async def _fetch_crawl_api(url: str) -> WebFetchResult:
    api_url = app_config.agent_crawl_api_url
    if not api_url:
        raise ValueError("Crawl API URL is not configured")
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if app_config.agent_crawl_api_token:
        headers["Authorization"] = f"Bearer {app_config.agent_crawl_api_token}"

    payload: dict[str, Any] = {
        "urls": [url],
        "browser_config": {"headless": True},
        "crawler_config": {
            "word_count_threshold": 10,
            "excluded_tags": ["nav", "footer", "aside", "script", "style"],
            "exclude_external_images": True,
        },
    }

    timeout = aiohttp.ClientTimeout(total=app_config.agent_crawl_api_timeout)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            f"{api_url.rstrip('/')}/crawl",
            json=payload,
            headers=headers,
        ) as resp:
            if resp.status == 408:
                return WebFetchResult(
                    success=False,
                    url=url,
                    error="Crawl API timed out",
                )
            resp.raise_for_status()
            data: dict[str, Any] = await resp.json()

    if not data.get("success"):
        results = data.get("results") or []
        err = results[0].get("error_message") if results else None
        return WebFetchResult(
            success=False,
            url=url,
            error=err or "Crawl API returned failure",
        )

    results = data.get("results") or []
    if not results:
        return WebFetchResult(
            success=False,
            url=url,
            error="Crawl API returned no results",
        )

    md = results[0].get("markdown") or {}
    text: str = md.get("raw_markdown", "") if isinstance(md, dict) else str(md)
    if not text.strip():
        return WebFetchResult(
            success=False,
            url=url,
            error="Page returned empty content",
        )
    return WebFetchResult(success=True, url=url, content=_truncate(text))


async def webfetch(ctx: RunContext[datatype.ContextDeps], url: str) -> WebFetchResult:
    """Fetch a web page and return its content as Markdown.
    Args:
        url: Full URL to fetch (http:// or https://).
    """
    if not url.startswith(("http://", "https://")):
        raise ModelRetry("URL must start with http:// or https://")
    try:
        if app_config.agent_crawl_api_url:
            return await _fetch_crawl_api(url)
        return await _fetch_http(url)
    except Exception as e:
        logger.error(f"webfetch error for {url}: {e.__class__.__name__}: {e}")
        return WebFetchResult(
            success=False,
            url=url,
            error=f"{e.__class__.__name__}: {e}",
        )


__all__ = ["webfetch"]
