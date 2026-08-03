from __future__ import annotations

import hashlib
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import httpx
from lxml import html as lxml_html

from kmua import common
from kmua.logger import logger

_CACHE_TTL = 3600
_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

_COOLAPK_RE = re.compile(r"https?://www\.coolapk\.com/(?:feed|picture)/\S+")
_TIEBA_RE = re.compile(r"https?://tieba\.baidu\.com/p/\d+")

# One combined pattern for handlers that must exclude these links (e.g. the
# agent wake filter) and for the chat plugin's own message filter.
SOCIAL_URL_RE = re.compile(
    r"(?:" + "|".join(p.pattern for p in (_COOLAPK_RE, _TIEBA_RE)) + ")"
)

# Trailing punctuation that Telegram's link autodetection may glue to the URL.
_TRAILING_PUNCT = "，。,.!?！？;；、"


@dataclass(slots=True)
class SocialPost:
    """One parsed post: platform-agnostic text + media."""

    source: str
    url: str
    title: str = ""
    text: str = ""
    images: list[str] = field(default_factory=list)
    video_url: str | None = None


def match_social_url(text: str) -> tuple[str, str] | None:
    """Return (source, url) for the first supported link in *text*, else None.

    Sources: "coolapk", "tieba".
    """
    for source, pattern in (
        ("coolapk", _COOLAPK_RE),
        ("tieba", _TIEBA_RE),
    ):
        match = pattern.search(text)
        if match:
            return source, match.group(0).rstrip(_TRAILING_PUNCT)
    return None


# ---------------------------------------------------------------------------
# Coolapk: plain page scrape


async def _fetch_coolapk(url: str) -> SocialPost | None:
    async with httpx.AsyncClient(
        timeout=_TIMEOUT, headers={"User-Agent": _UA}, follow_redirects=True
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        doc = lxml_html.fromstring(resp.text)

    def by_class(class_name: str) -> list:
        return doc.xpath(
            f'//*[contains(concat(" ", normalize-space(@class), " "), " {class_name} ")]'
        )

    title_nodes = by_class("message-title")
    title = title_nodes[0].text_content().strip() if title_nodes else ""
    content_nodes = by_class("feed-article-message")
    if content_nodes:
        text = _collapse_ws(content_nodes[0].text_content())
        images = [
            "https:" + img.get("src")
            for img in content_nodes[0].xpath(
                './/img[contains(@class, "message-image")]'
            )
            if (img.get("src") or "").startswith("//")
        ]
        if not images:
            images = [
                img.get("src")
                for img in content_nodes[0].xpath(
                    './/img[contains(@class, "message-image")]'
                )
                if (img.get("src") or "").startswith("http")
            ]
        if title or text:
            return SocialPost("coolapk", url, title, text, images)

    feed_nodes = by_class("feed-message")
    if feed_nodes and (text := _collapse_ws(feed_nodes[0].text_content())):
        images: list[str] = []
        groups = by_class("message-image-group")
        if groups:
            for img in groups[0].xpath(".//img"):
                src = img.get("src") or ""
                if src.startswith("//"):
                    images.append("https:" + src)
                elif src.startswith("http"):
                    images.append(src)
        return SocialPost("coolapk", url, "", text, images)
    return None


# ---------------------------------------------------------------------------
# Tieba: anonymous signed API (tbs + md5 signature, no login)


_TIEBA_SALT = "36770b1f34c9bbf2e7d1a99d2b82fa9e"


def _tieba_sign(params: dict[str, str]) -> str:
    base = "".join(f"{k}={v}" for k, v in sorted(params.items()))
    return hashlib.md5((base + _TIEBA_SALT).encode("utf-8")).hexdigest()


async def _fetch_tieba(url: str) -> SocialPost | None:
    kz_match = re.search(r"/p/(\d+)", url)
    if not kz_match:
        return None
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        tbs_resp = await client.get("http://tieba.baidu.com/dc/common/tbs")
        tbs_resp.raise_for_status()
        tbs = (tbs_resp.json() or {}).get("tbs")
        if not tbs:
            return None
        data = {
            "pn": "1",
            "lz": "0",
            "r": "2",
            "mark_type": "0",
            "back": "0",
            "fr": "personalize_page",
            "kz": kz_match.group(1),
            "session_request_times": "1",
            "tbs": tbs,
            "subapp_type": "pc",
            "_client_type": "20",
        }
        data["sign"] = _tieba_sign(data)
        resp = await client.post("https://tieba.baidu.com/c/f/pb/page_pc", data=data)
        resp.raise_for_status()
        result = resp.json()
    if result.get("error_code") not in (None, 0, "0"):
        logger.debug(f"link_parse: tieba error {result.get('error_code')} for {url}")
        return None
    thread = result.get("thread") or {}
    origin = thread.get("origin_thread_info") or {}
    title = (origin.get("title") or "").strip()
    content_parts: list[str] = []
    for item in origin.get("content") or []:
        if isinstance(item, dict) and item.get("type") == 0:
            content_parts.append(item.get("text") or "")
    text = "\n".join(part for part in content_parts if part.strip()).strip()
    images: list[str] = []
    for media in origin.get("media") or []:
        if isinstance(media, dict) and media.get("big_pic"):
            images.append(media["big_pic"])
    video_url = None
    video_info = thread.get("video_info") or {}
    if video_info.get("video_url"):
        video_url = video_info["video_url"]
    if not title and not text:
        return None
    return SocialPost("tieba", url, title, text, images, video_url)


# ---------------------------------------------------------------------------
# Dispatch


_FETCHERS: dict[str, Callable[[str], Awaitable[SocialPost | None]]] = {
    "coolapk": _fetch_coolapk,
    "tieba": _fetch_tieba,
}


async def fetch_social_post(url: str) -> SocialPost | None:
    """Parse one social link; cached per URL for an hour. None on failure.

    Raises nothing: a failed parse must not break message handling.
    """
    matched = match_social_url(url)
    if matched is None:
        return None
    source, clean_url = matched
    cache_key = f"social:{source}:{clean_url}"
    cached = await common.memttlcache.get(cache_key)
    if cached is not None:
        return cached
    try:
        post = await _FETCHERS[source](clean_url)
    except Exception as e:
        logger.warning(
            f"link_parse: {source} fetch failed for {url}: {e.__class__.__name__}: {e}"
        )
        return None
    if post is not None and (post.title or post.text or post.images or post.video_url):
        await common.memttlcache.set(cache_key, post, ttl=_CACHE_TTL)
    return post


def _collapse_ws(text: str) -> str:
    return re.sub(r"[ \t\r\n\u00a0]+", " ", text).strip()


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


__all__ = [
    "SocialPost",
    "fetch_social_post",
    "match_social_url",
    "truncate",
]
