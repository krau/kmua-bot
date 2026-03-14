import re
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlparse

import aiohttp
from crawl4ai import AsyncWebCrawler, CacheMode, CrawlerRunConfig, HTTPCrawlerConfig
from crawl4ai.async_crawler_strategy import AsyncHTTPCrawlerStrategy
from crawl4ai.models import CrawlResult, StringCompatibleMarkdown
from pydantic_ai import ModelRetry, RunContext
from pyrogram.errors import ChannelInvalid, ChannelPrivate, MessageIdsEmpty
from pyrogram.types import Message

from kmua.config import app_config
from kmua.database import get_chat_by_id
from kmua.logger import logger

from .. import datatype

MAX_CONTENT_LENGTH = 64000

_http_strategy = AsyncHTTPCrawlerStrategy(
    browser_config=HTTPCrawlerConfig(method="GET", verify_ssl=False)
)

_run_config = CrawlerRunConfig(
    cache_mode=CacheMode.ENABLED,
    word_count_threshold=10,
    excluded_tags=["nav", "footer", "aside", "script", "style"],
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


def _is_telegram_url(url: str) -> bool:
    """Check if URL is a Telegram domain link."""
    try:
        parsed = urlparse(url)
        return parsed.netloc.lower() in ("t.me", "telegram.me")
    except Exception:
        return False


def _parse_telegram_message_url(url: str) -> tuple[str | None, int | None, int | None]:
    """Parse Telegram message URL and return (username_or_chat_id, message_id, comment_id).

    Returns:
        Tuple of (username_or_chat_id, message_id, comment_id).
        For private chats (t.me/c/xxx), username_or_chat_id is the chat_id as string (without -100 prefix).
        For public chats (t.me/username), username_or_chat_id is the username.
        comment_id is only present for comments section URLs.
    """
    if not _is_telegram_url(url):
        return (None, None, None)

    # Match patterns:
    # https://t.me/c/23333333/2252 (private chat)
    # https://t.me/group_username/142727 (public chat)
    # https://t.me/channel_username/14816?comment=142730 (comment)
    patterns = [
        # Private chat: https://t.me/c/123456789/123
        r"https?://t\.me/c/(\d+)/(\d+)",
        # Public chat or comment: https://t.me/username/123 or https://t.me/username/123?comment=456
        r"https?://t\.me/([a-zA-Z0-9_]{5,32})/(\d+)(?:\?comment=(\d+))?",
    ]

    for pattern in patterns:
        match = re.match(pattern, url)
        if match:
            groups = match.groups()
            if len(groups) >= 2:
                username_or_id = groups[0]
                message_id = int(groups[1])
                comment_id = int(groups[2]) if len(groups) > 2 and groups[2] else None
                return (username_or_id, message_id, comment_id)

    return (None, None, None)


async def _fetch_telegram_message(
    ctx: RunContext[datatype.ContextDeps], url: str
) -> WebFetchResult | None:
    """Fetch Telegram message using client if allowed by privacy settings.

    Only fetches messages from:
    1. Public groups/channels (have username)
    2. Current chat

    Returns None if URL is not a Telegram message link or access is not allowed.
    """
    parsed = _parse_telegram_message_url(url)
    username_or_id, message_id, comment_id = parsed

    if username_or_id is None or message_id is None:
        return None

    client = ctx.deps.client
    current_chat_id = ctx.deps.chat_id

    try:
        # Determine target chat
        if username_or_id.isdigit():
            # Private chat (t.me/c/xxx)
            # Convert to full chat_id format (-100xxxxxxxxx)
            target_chat_id = int(f"-100{username_or_id}")

            # Only allow if it's the current chat
            if target_chat_id != current_chat_id:
                return WebFetchResult(
                    success=False,
                    url=url,
                    error="This is a Telegram message link but you cannot access private group/channel messages from other chats for privacy reasons",
                )
        else:
            # Public chat with username
            # Check if it's the current chat by looking up in database
            current_chat_data = await get_chat_by_id(current_chat_id)
            if (
                current_chat_data
                and current_chat_data.username
                and current_chat_data.username.lower() == username_or_id.lower()
            ):
                target_chat_id = current_chat_id
            else:
                # It's a different public chat, allow it but we'll try to get it by username
                target_chat_id = username_or_id

        # Fetch the message
        if comment_id:
            # It's a comment - fetch the comment message
            # Comments are in a linked discussion group, we need to get the original post first
            try:
                original_msg = await client.get_messages(target_chat_id, message_id)
                if not original_msg:
                    return WebFetchResult(
                        success=False,
                        url=url,
                        error="Original message not found",
                    )

                # The comment is in the linked chat (discussion group)
                if original_msg.link:
                    # Try to fetch the comment directly if possible
                    # Comments are typically in the discussion group
                    comment_msg = await client.get_messages(target_chat_id, comment_id)
                    if comment_msg:
                        return _format_telegram_message(
                            comment_msg, url, is_comment=True
                        )
            except Exception as e:
                logger.warning(f"Failed to fetch comment from {url}: {e}")
                # Fallback: try to fetch at least the original message
                pass

        # Fetch main message
        message = await client.get_messages(target_chat_id, message_id)
        if not message:
            return WebFetchResult(
                success=False,
                url=url,
                error="Message not found or access denied",
            )

        return _format_telegram_message(message, url)

    except (ChannelInvalid, ChannelPrivate):
        return WebFetchResult(
            success=False,
            url=url,
            error="Cannot access this chat - it may be private or you are not a member",
        )
    except MessageIdsEmpty:
        return WebFetchResult(
            success=False,
            url=url,
            error="Message not found",
        )
    except Exception as e:
        logger.warning(f"Failed to fetch Telegram message from {url}: {e}")
        return None


def _format_telegram_message(
    message: Message, url: str, is_comment: bool = False
) -> WebFetchResult:
    """Format a Telegram message into WebFetchResult."""
    parts = []

    # Add prefix for comments
    if is_comment:
        parts.append("[This is a comment/reply message]")

    # Sender info
    sender_name = "Unknown"
    if message.from_user:
        sender_name = message.from_user.first_name or ""
        if message.from_user.last_name:
            sender_name += f" {message.from_user.last_name}"
        if message.from_user.username:
            sender_name += f" (@{message.from_user.username})"
    elif message.sender_chat:
        sender_name = message.sender_chat.title or "Channel"

    parts.append(f"From: {sender_name}")

    # Date
    if message.date:
        parts.append(f"Date: {message.date.isoformat()}")

    # Message content
    content_parts = []

    if message.text:
        content_parts.append(message.text)

    if message.caption:
        content_parts.append(f"[Caption]: {message.caption}")

    # Handle media types
    if message.photo:
        content_parts.append("[Contains photo]")
    elif message.video:
        content_parts.append("[Contains video]")
    elif message.audio:
        content_parts.append(f"[Contains audio: {message.audio.title or 'Unknown'}]")
    elif message.voice:
        content_parts.append("[Contains voice message]")
    elif message.document:
        content_parts.append(
            f"[Contains document: {message.document.file_name or 'Unknown'}]"
        )
    elif message.sticker:
        content_parts.append(f"[Contains sticker: {message.sticker.emoji or ''}]")
    elif message.poll:
        content_parts.append(f"[Contains poll: {message.poll.question}]")

    # Forward info
    if message.forward_from or message.forward_from_chat:
        if message.forward_from_chat:
            fwd_name = message.forward_from_chat.title or "Unknown channel"
            if message.forward_from_message_id:
                fwd_name += f" (message {message.forward_from_message_id})"
        else:
            fwd_name = (
                message.forward_from.first_name if message.forward_from else "Unknown"
            )
        parts.append(f"Forwarded from: {fwd_name}")

    # Reply info
    if message.reply_to_message:
        parts.append(f"[This is a reply to message {message.reply_to_message.id}]")

    if content_parts:
        parts.append("\n--- Content ---\n" + "\n".join(content_parts))

    content = "\n".join(parts)
    return WebFetchResult(success=True, url=url, content=_truncate(content))


async def webfetch(ctx: RunContext[datatype.ContextDeps], url: str) -> WebFetchResult:
    """Fetch a web page and return its content as Markdown.
    Args:
        url: Full URL to fetch (http:// or https://).
    """
    if not url.startswith(("http://", "https://")):
        raise ModelRetry("URL must start with http:// or https://")

    # Try to fetch Telegram messages directly if it's a Telegram link
    if _is_telegram_url(url):
        tg_result = await _fetch_telegram_message(ctx, url)
        if tg_result is not None:
            return tg_result
        # If tg_result is None, fall through to normal web fetching

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
