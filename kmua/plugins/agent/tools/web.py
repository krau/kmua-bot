from dataclasses import dataclass
from typing import cast

from crawl4ai import AsyncWebCrawler, CacheMode, CrawlerRunConfig, HTTPCrawlerConfig
from crawl4ai.async_crawler_strategy import AsyncHTTPCrawlerStrategy
from crawl4ai.models import CrawlResult, StringCompatibleMarkdown
from pydantic_ai import RunContext

from kmua.logger import logger

from .. import datatype

MAX_CONTENT_LENGTH = 8000


@dataclass
class WebFetchResult:
    success: bool
    url: str
    content: str | None = None
    error: str | None = None


_http_strategy = AsyncHTTPCrawlerStrategy(
    browser_config=HTTPCrawlerConfig(method="GET", verify_ssl=False)
)

_run_config = CrawlerRunConfig(
    cache_mode=CacheMode.BYPASS,
    word_count_threshold=10,
    excluded_tags=["nav", "footer", "aside", "script", "style"],
    exclude_external_images=True,
)


async def webfetch(
    ctx: RunContext[datatype.ContextDeps],
    url: str,
) -> WebFetchResult:
    """Fetch the content of a web page and return it as clean Markdown text.

    Uses a lightweight HTTP-based crawler (no browser required) to retrieve and
    parse the page. Works well for static pages and server-rendered content.
    JavaScript-heavy single-page applications may return limited content.

    The returned Markdown is truncated to avoid exceeding context limits. If the
    page content is very long, only the first portion is returned — prefer
    targeted URLs (e.g. a specific article) over broad index pages.

    Args:
        url: The full URL to fetch (must start with http:// or https://).

    Returns:
        A WebFetchResult with:
        - success: whether the fetch succeeded
        - url: the fetched URL
        - content: page content as Markdown (None on failure)
        - error: error description (None on success)
    """
    logger.debug(f"webfetch called with url={url} by user_id={ctx.deps.user_id}")
    if not url.startswith(("http://", "https://")):
        return WebFetchResult(
            success=False,
            url=url,
            error="URL must start with http:// or https://",
        )
    try:
        async with AsyncWebCrawler(crawler_strategy=_http_strategy) as crawler:
            raw = await crawler.arun(url, config=_run_config)
        result = cast(CrawlResult, raw)
        if not result.success:
            logger.warning(f"webfetch failed for {url}: {result.error_message}")
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
        if len(text) > MAX_CONTENT_LENGTH:
            text = (
                text[:MAX_CONTENT_LENGTH]
                + f"\n\n[Content truncated at {MAX_CONTENT_LENGTH} characters]"
            )
        return WebFetchResult(success=True, url=url, content=text)
    except Exception as e:
        logger.error(f"webfetch error for {url}: {e.__class__.__name__}: {e}")
        return WebFetchResult(
            success=False,
            url=url,
            error=f"{e.__class__.__name__}: {e}",
        )


__all__ = ["webfetch"]
