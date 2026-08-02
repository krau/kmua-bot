"""Twitter/X article parsing via the FxEmbed (FxTwitter) API.

Fetches tweet data from a FxEmbed-compatible instance (default public
``https://api.fxtwitter.com``) and normalizes it for delivery: full text,
author, timestamp and media (photos, videos, gifs) in document order. Pure
parsing functions are separated from network I/O for testability.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from kmua.config import app_config
from kmua.logger import logger

# twitter.com/<handle>/status/<id> or x.com/... (no scheme, substring match)
TWITTER_URL_RE = re.compile(r"(?:twitter|x)\.com/([^/]+)/status/(\d+)")

_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
_MAX_TEXT_CHARS = 4000
_MAX_MEDIA = 10


@dataclass(slots=True)
class TweetMedia:
    url: str
    kind: str  # "photo" | "video" | "gif"


@dataclass(slots=True)
class TweetData:
    url: str
    tweet_id: str
    text: str
    author_name: str
    author_screen_name: str
    created_timestamp: int | None = None
    media: list[TweetMedia] = field(default_factory=list)
    quote_text: str | None = None


def extract_tweet_id(text: str) -> str | None:
    """Extract the numeric tweet id from a twitter/x.com status URL."""
    match = TWITTER_URL_RE.search(text)
    if not match:
        return None
    return match.group(2)


def parse_tweet_response(data: dict[str, Any], tweet_url: str) -> TweetData | None:
    """Normalize a FxEmbed v2 response into TweetData.

    Pure function. Returns None when the response carries no status (deleted,
    private, rate-limited).
    """
    raw_status = data.get("status")
    if not isinstance(raw_status, dict):
        return None
    status: dict[str, Any] = raw_status
    tweet_id = str(status.get("id", ""))
    if not tweet_id:
        return None
    raw_author = data.get("author")
    author: dict[str, Any] = raw_author if isinstance(raw_author, dict) else {}
    media = status.get("media")
    media_items: list[TweetMedia] = []
    if isinstance(media, dict):
        for item in media.get("all") or []:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            kind = item.get("type")
            if (
                isinstance(url, str)
                and url.startswith("http")
                and kind
                in (
                    "photo",
                    "video",
                    "gif",
                )
            ):
                media_items.append(TweetMedia(url=url, kind=kind))
    quote = status.get("quote")
    quote_text = None
    if isinstance(quote, dict):
        quote_text = (quote.get("text") or "").strip() or None
    return TweetData(
        url=tweet_url,
        tweet_id=tweet_id,
        text=(status.get("text") or "").strip(),
        author_name=(author.get("name") or "").strip(),
        author_screen_name=(author.get("screen_name") or "").strip(),
        created_timestamp=status.get("created_timestamp"),
        media=media_items[:_MAX_MEDIA],
        quote_text=quote_text,
    )


async def fetch_tweet(url: str) -> TweetData | None:
    """Fetch one tweet from the FxEmbed API. None on any failure (404 etc.).

    Raises nothing: a failed fetch must not break message handling, the caller
    logs and moves on.
    """
    tweet_id = extract_tweet_id(url)
    if not tweet_id:
        return None
    api_url = f"{app_config.fxembed_api_url.rstrip('/')}/2/status/{tweet_id}"
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0 Safari/537.36"
                )
            },
        ) as client:
            resp = await client.get(api_url)
            if resp.status_code != 200:
                logger.debug(f"twitter: api {resp.status_code} for tweet {tweet_id}")
                return None
            data = resp.json()
    except Exception as e:
        logger.warning(f"twitter: fetch failed for {url}: {e.__class__.__name__}: {e}")
        return None
    tweet = parse_tweet_response(data, url)
    if tweet is None:
        logger.debug(f"twitter: no status in api response for {tweet_id}")
    return tweet


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def build_tweet_text(tweet: TweetData, lang: str = "zh-CN") -> str:
    """Rich HTML body for a media-less tweet (author, text, quote, link).

    Pure function. Every dynamic value is escaped for Telegram's HTML mode.
    """
    import html as html_mod

    from kmua import i18n

    lines: list[str] = []
    if tweet.author_name:
        handle = f"@{tweet.author_screen_name}" if tweet.author_screen_name else ""
        lines.append(
            f"<b>{html_mod.escape(tweet.author_name)}</b> {html_mod.escape(handle)}".rstrip()
        )
    if tweet.text:
        lines.append(
            f"<blockquote expandable=true>{html_mod.escape(truncate(tweet.text, _MAX_TEXT_CHARS))}</blockquote>"
        )
    if tweet.quote_text:
        lines.append(
            f"<blockquote expandable=true>🔁 {html_mod.escape(truncate(tweet.quote_text, 500))}</blockquote>"
        )
    meta: list[str] = []
    if tweet.created_timestamp:
        from datetime import datetime

        meta.append(
            html_mod.escape(
                datetime.fromtimestamp(tweet.created_timestamp).strftime("%Y-%m-%d")
            )
        )
    meta.append(
        f'<a href="{html_mod.escape(tweet.url)}">{html_mod.escape(i18n.t("bot.msg.twitter.view_original", locale=lang))}</a>'
    )
    lines.append(" · ".join(meta))
    return "\n".join(lines)


__all__ = [
    "TweetData",
    "TweetMedia",
    "TWITTER_URL_RE",
    "build_tweet_text",
    "extract_tweet_id",
    "fetch_tweet",
    "parse_tweet_response",
    "truncate",
]
