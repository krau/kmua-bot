"""Fetch, parse, and render RSS/Atom feeds.

Pure functions plus one async fetch — no Telegram or database access here, so the
rendering and identity logic is unit-testable without a bot.

Parsing is delegated to `feedparser`, which handles RSS 0.9x/1.0/2.0, Atom 0.3/1.0,
encoding sniffing, and broken markup. It is a synchronous library, so `fetch_feed`
runs `feedparser.parse` in a worker thread via `asyncio.to_thread` — the bot runs on
a single event loop and a blocking parse would stall message handling. For the same
reason the HTTP fetch is `httpx` async; feedparser's own fetch path uses blocking
urllib and is never used.

Feed content is untrusted remote data. There is no HTML sanitizer in this
repository, so this module IS the sanitizer: `_sanitize_html` reduces entry HTML to
the small tag set Telegram's HTML parse mode accepts (`b i u s blockquote code
pre`), escapes everything else, and balances the tags — Telegram refuses a message
with an unclosed entity. `render_entry` then emits that safe subset verbatim and
escapes only the strings it builds itself. Images are not embedded in text
(Telegram does not render `<img>`): they are extracted as URLs and delivered as a
photo message by the caller.
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import ipaddress
import re
import socket
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import feedparser
import httpx

from kmua import i18n

MAX_ENTRIES_PER_PUSH = 5
"""Cap per feed per poll. A feed that just published 200 items must not turn into
200 messages; the newest few are what a subscriber actually wants."""

MAX_FAILURES = 10
"""Consecutive failures after which a feed is skipped by the poll job."""

_MAX_TITLE_LEN = 200
_MAX_SUMMARY_LEN = 1024
"""Long enough for a full-text entry excerpt; also Telegram's photo caption limit,
so the same text fits either a text message or a photo caption."""
_MAX_MEDIA = 3
"""Images delivered per entry, at most. A gallery feed must not turn into ten
separate photo messages per entry."""
_MAX_BODY_BYTES = 5 * 1024 * 1024
"""Largest response body we will parse. A giant feed must not eat the process."""

_MAX_REDIRECTS = 5
"""Redirect hops we will follow; each hop is re-validated against the address
blocklist, so a public URL cannot tunnel into the internal network."""

_USER_AGENT = "KMUA Bot"

# Addresses a feed may never resolve to: private, loopback, link-local, CGNAT,
# documentation, multicast and reserved ranges (IPv4), plus loopback/ULA/
# link-local/multicast (IPv6). `ipaddress` covers most of these, but the ranges
# here are spelled out so the blocklist does not depend on library version
# semantics for the non-obvious ones.
_NON_PUBLIC_V4 = [
    ipaddress.ip_network(net)
    for net in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
    )
]
_NON_PUBLIC_V6 = [
    ipaddress.ip_network(net)
    for net in (
        "::/128",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
        "ff00::/8",
    )
]

# The tag set Telegram's HTML parse mode renders, which `_sanitize_html` keeps.
# It is the single source of truth: the kept-tag and token regexes are built
# from it so a new kept tag cannot be added in one place and forgotten in the
# other.
_KEPT_TAGS = ("b", "i", "u", "s", "blockquote", "code", "pre")

_KEPT_TAGS_ALT = "|".join(_KEPT_TAGS)
# Matches exactly our own emitted tags (no attributes, no surprises).
_KEPT_TAG_RE = re.compile(rf"</?({_KEPT_TAGS_ALT})>")
# `\x01o<tag>\x01` / `\x01c<tag>\x01`: tags the sanitizer emitted itself, hidden
# from the escape pass so source text cannot forge them. Inline formatting tags
# only - code/pre blocks use the `\x00` placeholder path instead.
_TAG_TOKEN_TAGS = "|".join(t for t in _KEPT_TAGS if t not in ("code", "pre"))
_TAG_TOKEN_RE = re.compile(rf"\x01([oc])({_TAG_TOKEN_TAGS})\x01")

# Block-level closing tags become paragraph breaks so the pushed text keeps the
# source layout instead of collapsing into one blob.
_BLOCK_CLOSE_RE = re.compile(
    r"</(?:p|div|li|h[1-6]|figure|figcaption|blockquote|tr|article|section|ul|ol|table|pre)>",
    re.IGNORECASE,
)
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_IMG_SRC_RE = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.IGNORECASE)
_SPACES_RE = re.compile(r"[ \t\xa0]+")
# `<pre>`/`<code>` blocks are protected verbatim (their content escaped) so code
# survives the tag-stripping pass intact.
_PRE_CODE_RE = re.compile(r"<(pre|code)\b[^>]*>(.*?)</\1>", re.IGNORECASE | re.DOTALL)
_INLINE_TAG_RE = re.compile(
    r"</?(strong|b|em|i|u|ins|s|strike|del|blockquote|a|[a-z][a-z0-9]*)\b[^>]*>",
    re.IGNORECASE,
)
_PLACEHOLDER_RE = re.compile(r"\x00(\d+)\x00")
_CTRL_ENTITY_RE = re.compile(r"&#(?:x[0-9a-fA-F]{1,6}|\d{1,7});?")

_ENTITY_TO_TAG = {
    "strong": "b",
    "em": "i",
    "strike": "s",
    "del": "s",
    "ins": "u",
}


@dataclass(slots=True)
class FeedEntry:
    entry_id: str
    title: str
    link: str
    summary: str
    media_urls: list[str] = field(default_factory=list)


@dataclass(slots=True)
class FetchResult:
    """Outcome of one poll. `not_modified` means a 304 — nothing to do."""

    not_modified: bool
    feed_title: str | None
    entries: list[FeedEntry]
    etag: str | None
    last_modified: str | None


def _plain_text(raw: str, limit: int) -> str:
    """Entry HTML reduced to plain text with paragraph breaks.

    Used for titles, where markup is noise. Block tags become blank lines,
    `<br>` a line break; everything else is stripped and entities unescaped.
    """
    text = raw or ""
    text = _BR_RE.sub("\n", text)
    text = _BLOCK_CLOSE_RE.sub("\n\n", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    return _collapse_lines(text)[:limit]


def _collapse_lines(text: str) -> str:
    """Trim each line, keep at most one blank line between paragraphs, and
    collapse runs of spaces (not newlines)."""
    lines = [line.strip() for line in text.split("\n")]
    out: list[str] = []
    for line in lines:
        if not line:
            if out and out[-1]:
                out.append("")
            continue
        out.append(line)
    collapsed = "\n".join(out).strip("\n")
    return _SPACES_RE.sub(" ", collapsed)


def _escape_text_parts(text: str) -> str:
    """Escape everything, then restore the tags the sanitizer emitted itself.

    The kept tags are hidden behind `\x01` tokens during unescape + escape, so a
    literal `&lt;b&gt;` in the source (unescaped to `<b>`) is escaped back to
    text while our own tags come back untouched.
    """
    escaped = html.escape(text, quote=False)
    return _TAG_TOKEN_RE.sub(
        lambda m: f"{'</' if m.group(1) == 'c' else '<'}{m.group(2)}>", escaped
    )


def _balance_tags(text: str) -> str:
    """Drop tags that do not close, so Telegram never sees an unclosed entity.

    Operates only on the kept tag set; the content of a dropped tag is kept.
    """
    out: list[str] = []
    stack: list[tuple[str, int]] = []
    pos = 0
    for match in _KEPT_TAG_RE.finditer(text):
        out.append(text[pos : match.start()])
        token = match.group(0)
        name = match.group(1).lower()
        if token.startswith("</"):
            if stack and stack[-1][0] == name:
                stack.pop()
                out.append(f"</{name}>")
            # Stray closing tag: dropped with its text kept.
        else:
            stack.append((name, len(out)))
            out.append(f"<{name}>")
        pos = match.end()
    out.append(text[pos:])
    for _, index in stack:
        out[index] = ""
    return "".join(out)


def _strip_ctrl_entities(text: str) -> str:
    """Remove numeric character references that decode to control characters.

    `html.unescape` turns `&#1;` into a literal `\x01`; that byte is the
    sanitizer's own tag-token sentinel, so a feed could forge a token and have
    it restored as a real tag. Control characters are meaningless in feed text,
    so their entity forms are dropped before the unescape pass instead of
    special-casing the sentinels.
    """

    def repl(match: re.Match) -> str:
        raw = match.group(0)
        digits = raw[2:-1] if raw.endswith(";") else raw[2:]
        try:
            codepoint = int(digits, 16) if digits[:1].lower() == "x" else int(digits)
        except ValueError:
            return raw
        if codepoint <= 0x20 or 0x7F <= codepoint <= 0x9F:
            return ""
        return raw

    return _CTRL_ENTITY_RE.sub(repl, text)


def _sanitize_html(raw: str, limit: int) -> str:
    """Reduce entry HTML to the Telegram-safe tag subset.

    Keeps `b i u s blockquote code pre` (with strong/em/strike/del/ins mapped),
    preserves paragraph breaks, escapes everything else, and balances the tags.
    The result is safe to emit verbatim with `parse_mode=HTML`.
    """
    text = raw or ""

    # 1. Protect code blocks so their content (which may contain tags, `<` or
    #    newlines) survives the passes below untouched and escaped.
    placeholders: list[str] = []

    def protect(match: re.Match) -> str:
        tag = match.group(1).lower()
        body = match.group(2)
        # `<pre><code class="language-x">…</code></pre>` is the common wrapper on
        # real feeds; strip the inner code tags (and their attributes) so the
        # label text never shows up inside the rendered block.
        body = re.sub(r"</?code\b[^>]*>", "", body, flags=re.IGNORECASE)
        # `<br>` inside a block is a line break, not literal text.
        body = _BR_RE.sub("\n", body)
        # Unescape once before escaping: feeds frequently ship pre-escaped code
        # (`&lt;` for `<`), and escaping the entity would double-escape it.
        body = html.escape(html.unescape(body), quote=False)
        placeholders.append(f"<{tag}>{body}</{tag}>")
        return f"\x00{len(placeholders) - 1}\x00"

    text = _PRE_CODE_RE.sub(protect, text)

    # 1b. Drop control-character entities before unescape so they cannot forge
    #     the sentinels below; then line/paragraph structure.
    text = _strip_ctrl_entities(text)

    # 2. Line/paragraph structure; HTML comments are noise, not content.
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = _BR_RE.sub("\n", text)
    text = _BLOCK_CLOSE_RE.sub("\n\n", text)

    # 3. One pass over every tag: inline formatting tags map onto the kept set
    #    (hidden behind \x01 tokens for now), everything else (anchors, images,
    #    scripts, ...) is dropped with its visible text kept.
    def inline(match: re.Match) -> str:
        token = match.group(0)
        closing = token.startswith("</")
        name = _ENTITY_TO_TAG.get(match.group(1).lower(), match.group(1).lower())
        if name not in {"b", "i", "u", "s", "blockquote"}:
            return ""
        return f"\x01{'c' if closing else 'o'}{name}\x01"

    text = _INLINE_TAG_RE.sub(inline, text)

    # 4. Unescape, then re-escape everything that is not one of our tags.
    text = _escape_text_parts(html.unescape(text))

    # 5. Collapse layout.
    text = _collapse_lines(text)

    # 6. Truncate; a cut through a placeholder drops that code block entirely
    #    rather than emitting a broken one. Placeholder indices from source text
    #    (a literal NUL byte cannot be decoded from an entity, but be safe) are
    #    bounds-checked so a forged index cannot crash the fetch.
    text = text[:limit]

    def restore(match: re.Match) -> str:
        index = int(match.group(1))
        if 0 <= index < len(placeholders):
            return placeholders[index]
        return ""

    text = _PLACEHOLDER_RE.sub(restore, text)
    text = re.sub(r"\x00\d*\x00?", "", text)

    # 7. Balance.
    return _balance_tags(text)


def _entry_html(raw_entry) -> str:
    """The richest HTML body an entry carries: content, else summary/description.

    `content` is the full article on real-world feeds (content:encoded, Atom
    content); summary/description is often just an excerpt or even the bare title.
    """
    html_parts = "".join(
        c.get("value", "") or "" for c in raw_entry.get("content") or []
    )
    if html_parts:
        return html_parts
    return raw_entry.get("summary") or raw_entry.get("description") or ""


def _extract_media(raw_html: str, raw_entry, base: str) -> list[str]:
    """Image URLs for one entry: `<img>` in the body, then enclosures.

    Relative URLs are resolved against the feed's own base. Only http(s) URLs are
    kept - Telegram's photo-by-URL path accepts https (and http is refused by
    Telegram), and data: URIs cannot be pushed at all.
    """
    urls: list[str] = []
    for src in _IMG_SRC_RE.findall(raw_html or ""):
        urls.append(urljoin(base, src))
    for enc in raw_entry.get("enclosures") or []:
        if str(enc.get("type", "")).startswith("image/"):
            urls.append(urljoin(base, enc.get("url", "")))
    for media in raw_entry.get("media_content") or []:
        if str(media.get("type", "")).startswith("image/"):
            urls.append(urljoin(base, media.get("url", "")))
    for thumb in raw_entry.get("media_thumbnail") or []:
        urls.append(urljoin(base, thumb.get("url", "")))

    seen: list[str] = []
    for url in urls:
        if url.startswith(("http://", "https://")) and url not in seen:
            seen.append(url)
        if len(seen) >= _MAX_MEDIA:
            break
    return seen


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True when `ip` may not be contacted by the fetcher."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    networks = (
        _NON_PUBLIC_V4 if isinstance(ip, ipaddress.IPv4Address) else _NON_PUBLIC_V6
    )
    return any(ip in net for net in networks)


async def _validate_url(url: str) -> None:
    """Reject URLs that would reach anything but a public internet address.

    Resolves the host and refuses the fetch when any address is private,
    loopback, link-local, CGNAT, metadata (169.254.0.0/16 covers the cloud
    metadata endpoint), or otherwise non-routable. This is the SSRF guard: it
    runs on the original URL and on every redirect hop.
    """
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"unsupported scheme: {parsed.scheme!r}")
    if parsed.username is not None or parsed.password is not None:
        # A signed feed URL would otherwise leak its credentials into logs and
        # error stores; refuse rather than redact-by-accident.
        raise ValueError("feed URLs may not carry credentials")
    host = parsed.hostname
    if not host:
        raise ValueError("feed URL has no host")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        raise ValueError("feed URL has an invalid port")
    infos = await asyncio.to_thread(
        socket.getaddrinfo, host, port, type=socket.SOCK_STREAM
    )
    if not infos:
        raise ValueError("feed host does not resolve")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if _is_blocked_ip(ip):
            raise ValueError(f"feed host resolves to a non-public address: {ip}")


def redact_url(url: str) -> str:
    """Strip query, fragment and userinfo from a URL for logs and error stores.

    A signed feed URL (`?token=...`) must not have its secret persisted into
    logs, the audit trail, or `last_error`; the feed row itself keeps the raw
    URL because fetching needs it.
    """
    try:
        parsed = urlsplit(url)
    except ValueError:
        return "<invalid url>"
    if parsed.scheme not in ("http", "https"):
        return url
    host = parsed.hostname or ""
    try:
        if parsed.port:
            host = f"{host}:{parsed.port}"
    except ValueError:
        pass
    return f"{parsed.scheme}://{host}{parsed.path}"


async def fetch_feed(
    url: str, *, etag: str | None = None, last_modified: str | None = None
) -> FetchResult:
    """Fetch and parse one feed.

    Raises `httpx.HTTPError` / `ValueError` on failure; the caller records it.
    The body is streamed and aborted past `_MAX_BODY_BYTES` rather than buffered
    whole first. Redirects are followed by hand, re-validating each hop against
    the address blocklist (a public URL must not tunnel into the internal
    network).
    """
    headers = {"User-Agent": _USER_AGENT}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30, connect=10),
        follow_redirects=False,
        headers=headers,
    ) as client:
        current = url
        content: bytes = b""
        for _ in range(_MAX_REDIRECTS + 1):
            await _validate_url(current)
            async with client.stream("GET", current) as resp:
                if resp.status_code in (301, 302, 303, 307, 308):
                    location = resp.headers.get("location")
                    if not location:
                        break
                    current = urljoin(current, location)
                    continue
                if resp.status_code == 304:
                    return FetchResult(
                        not_modified=True,
                        feed_title=None,
                        entries=[],
                        etag=etag,
                        last_modified=last_modified,
                    )
                resp.raise_for_status()

                chunks: list[bytes] = []
                size = 0
                async for chunk in resp.aiter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > _MAX_BODY_BYTES:
                        raise ValueError("feed too large")
                content = b"".join(chunks)
                break
        else:
            raise ValueError("too many redirects")

    parsed = await asyncio.to_thread(feedparser.parse, content)

    if parsed.bozo and not parsed.entries:
        raise ValueError(f"malformed feed: {parsed.get('bozo_exception')}")

    # Base for resolving relative entry links and image srcs. Many feeds use
    # absolute URLs, but relative ones are common enough (e.g. `/artwork/...`)
    # that pushing a broken link is a real outcome without this.
    feed_link = parsed.feed.get("link") or "" if parsed.feed else ""
    base = feed_link if feed_link.startswith(("http://", "https://")) else url

    entries = []
    for raw in parsed.entries[: MAX_ENTRIES_PER_PUSH * 4]:
        link = urljoin(base, raw.get("link", "") or "")
        if not link.startswith(("http://", "https://")):
            # An entry link of another scheme would land in the message's href
            # verbatim; drop it rather than emit a javascript:/data: link.
            link = ""
        entries.append(
            FeedEntry(
                entry_id=entry_id_of(raw),
                title=_plain_text(raw.get("title", ""), _MAX_TITLE_LEN),
                link=link,
                summary=_sanitize_html(_entry_html(raw), _MAX_SUMMARY_LEN),
                media_urls=_extract_media(_entry_html(raw), raw, base),
            )
        )

    return FetchResult(
        not_modified=False,
        feed_title=(parsed.feed.get("title") or None) if parsed.feed else None,
        entries=entries,
        etag=resp.headers.get("ETag"),
        last_modified=resp.headers.get("Last-Modified"),
    )


def entry_id_of(raw_entry) -> str:
    """Stable identity for an entry: `id`, else `link`, else a sha256 of title+summary.

    A feed with neither id nor link is rare but real; hashing the content keeps such a
    feed from re-pushing every single poll.
    """
    entry_id = raw_entry.get("id") or raw_entry.get("link")
    if entry_id:
        return str(entry_id)
    digest = hashlib.sha256()
    digest.update(str(raw_entry.get("title", "")).encode("utf-8", "replace"))
    digest.update(b"\0")
    digest.update(str(raw_entry.get("summary", "")).encode("utf-8", "replace"))
    return digest.hexdigest()


def render_entry(feed_title: str, entry: FeedEntry, lang: str) -> str:
    """Build the HTML message body for one entry.

    `entry.summary` is already restricted to the safe tag set by `_sanitize_html`
    and is emitted verbatim; every other remote string is escaped here.
    """
    title = entry.title or i18n.t("bot.msg.rss.untitled", locale=lang)
    escaped_title = html.escape(title)
    escaped_feed_title = html.escape(feed_title)

    lines = [f"📰 <b>{escaped_feed_title}</b>"]
    if entry.link:
        lines.append(f'<a href="{html.escape(entry.link)}">{escaped_title}</a>')
    else:
        lines.append(f"<b>{escaped_title}</b>")
    if entry.summary:
        lines.append("")
        lines.append(entry.summary)
    return "\n".join(lines)


def truncate_for_delivery(text: str, limit: int) -> str:
    """Shrink a rendered message to fit `limit` without breaking HTML.

    Prefers a paragraph boundary (blank line), then a line break, then a bare
    character cut. The result is re-balanced so Telegram never sees an unclosed
    entity, and an ellipsis is appended when anything was dropped.
    """
    if len(text) <= limit:
        return text
    head = text[:limit]
    cut = head.rfind("\n\n")
    if cut < limit // 2:
        cut = head.rfind("\n")
    if cut < limit // 2:
        cut = limit
    snippet = text[:cut].rstrip()
    return _balance_tags(snippet) + " …"


__all__ = [
    "MAX_ENTRIES_PER_PUSH",
    "MAX_FAILURES",
    "FeedEntry",
    "FetchResult",
    "entry_id_of",
    "redact_url",
    "fetch_feed",
    "render_entry",
    "truncate_for_delivery",
]
