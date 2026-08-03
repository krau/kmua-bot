"""WeChat (Weixin) official-account article parsing.

Fetches mp.weixin.qq.com article pages and extracts the title, author, body
text and image URLs. Pure functions are separated from network I/O so the
parsing logic is unit-testable without touching the network.
"""

from __future__ import annotations

import asyncio
import html as html_mod
import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from lxml import html as lxml_html
from PIL import Image

_WECHAT_HOST = "mp.weixin.qq.com"
_IMAGE_HOSTS = ("mmbiz.qpic.cn", "mmbiz.wxpic.cn")
_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# Article short links: https://mp.weixin.qq.com/s/<id>
WECHAT_URL_RE = re.compile(r"https?://mp\.weixin\.qq\.com/s/[A-Za-z0-9_-]+")

_MAX_BODY_CHARS = 3500
_MAX_PARAGRAPH_CHARS = 500
_MAX_IMAGES = 10


@dataclass(slots=True)
class WechatBlock:
    """One body item in document order: a text paragraph or an image URL."""

    kind: str  # "text" | "image"
    content: str


@dataclass(slots=True)
class WechatArticle:
    url: str
    title: str = ""
    author: str | None = None
    published_at: datetime | None = None
    paragraphs: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    blocks: list[WechatBlock] = field(default_factory=list)
    description: str = ""


def is_wechat_url(url: str) -> bool:
    """True for a https://mp.weixin.qq.com/s/<id> link (host-exact, no userinfo)."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return (
        parts.scheme == "https"
        and parts.netloc == _WECHAT_HOST
        and bool(re.fullmatch(r"[A-Za-z0-9_-]+", parts.path.removeprefix("/s/")))
        and parts.path.startswith("/s/")
    )


def _is_wechat_image_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return (
        parts.scheme in ("http", "https")
        and parts.hostname is not None
        and (
            parts.hostname == _IMAGE_HOSTS[0]
            or parts.hostname.endswith("." + _IMAGE_HOSTS[0])
        )
        or (
            parts.hostname == _IMAGE_HOSTS[1]
            or (parts.hostname or "").endswith("." + _IMAGE_HOSTS[1])
        )
    )


def _meta_content(doc: Any, prop: str) -> str | None:
    nodes = doc.xpath(f'//meta[@property="{prop}"]/@content')
    if nodes:
        return nodes[0].strip()
    return None


def _normalize_newlines(text: str) -> str:
    """Convert WeChat's literal ``\\x0a`` / ``\\n`` escapes to real newlines
    and drop zero-width characters (ZWNJ etc.) that WeChat sprinkles between
    paragraphs; they render as phantom blank lines inside block quotes.
    """
    text = re.sub(r"\\x0a", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"\\n", "\n", text)
    return re.sub(r"[\u200b-\u200f\ufeff]", "", text)


# Elements that start a new paragraph. Everything else (span, section, div,
# a, em, ...) is treated as inline: its text folds into the current paragraph
# and whitespace around it collapses to a single space, so formatted HTML
# can never split every word onto its own line.
_PARAGRAPH_TAGS = frozenset(
    {"p", "blockquote", "li", "pre", "h1", "h2", "h3", "h4", "h5", "h6"}
)


def _paragraphs_from_html(raw_html: str) -> list[str]:
    """Body text as paragraphs, split on real block elements only.

    WeChat stores the body as a stream of ``<span>`` leaves wrapped in nested
    ``<section>``s; the block boundaries that matter are ``<p>`` and ``<br>``.
    Inline elements and the whitespace between them fold into the current
    paragraph, so a formatted/pretty-printed page (or one whose spans carry
    stray newlines) does not split every word onto its own line.
    """
    return [b.content for b in _blocks_from_html(raw_html) if b.kind == "text"]


def _images_from_html(raw_html: str) -> list[str]:
    """Image URLs from #js_content <img> tags (data-src first, then src)."""
    doc = lxml_html.fromstring(raw_html)
    node = doc.xpath('//*[@id="js_content"]')
    if not node:
        return []
    urls: list[str] = []
    for img in node[0].xpath(".//img"):
        url = img.get("data-src") or img.get("src") or ""
        if _is_wechat_image_url(url):
            urls.append(url)
    return urls[:_MAX_IMAGES]


def _blocks_from_html(raw_html: str) -> list[WechatBlock]:
    """Body items in document order: paragraphs interleaved with images.

    Walks the #js_content tree treating ``<p>``/``<blockquote>``/``<li>`` and
    ``<br>`` as paragraph boundaries; ``<img>`` becomes an image block in
    place. Every other tag (``<span>``, ``<section>``, ``<a>``, ...) is inline:
    its text and the whitespace around it join the current paragraph, so the
    rich message reads as continuous text instead of one line per word.
    """
    doc = lxml_html.fromstring(raw_html)
    node = doc.xpath('//*[@id="js_content"]')
    if not node:
        return []

    raw_blocks: list[WechatBlock] = []
    segment: list[str] = []

    def fold(text: str) -> str:
        """Collapse any whitespace (including newlines inside text nodes)
        to a single space; only explicit <br> keeps a paragraph break."""
        return re.sub(r"[ \t\r\n\u00a0]+", " ", text)

    def flush() -> None:
        # Only collapse runs of spaces here; newlines (from <br>) survive so
        # the final split keeps real line breaks.
        text = re.sub(r"[ \t\r\u00a0]{2,}", " ", "".join(segment)).strip()
        if text:
            raw_blocks.append(WechatBlock(kind="text", content=text))
        segment.clear()

    def visit(el: Any) -> None:
        if not isinstance(el.tag, str):
            return
        tag = el.tag.lower()
        if tag == "img":
            flush()
            url = el.get("data-src") or el.get("src") or ""
            if _is_wechat_image_url(url):
                raw_blocks.append(WechatBlock(kind="image", content=url))
            return
        if tag == "br":
            segment.append("\n")
            return
        if tag in _PARAGRAPH_TAGS:
            flush()
            if el.text:
                segment.append(fold(el.text))
            for child in el:
                visit(child)
                if child.tail:
                    segment.append(fold(child.tail))
            flush()
            return
        # inline / container: fold into the current segment
        if el.text:
            segment.append(fold(el.text))
        for child in el:
            visit(child)
            if child.tail:
                segment.append(fold(child.tail))

    visit(node[0])
    flush()

    # Normalize: convert WeChat \\x0a escapes, then split paragraphs on the
    # newlines that came from <br> boundaries.
    result: list[WechatBlock] = []
    image_count = 0
    for block in raw_blocks:
        if block.kind == "image":
            if image_count < _MAX_IMAGES:
                image_count += 1
                result.append(block)
            continue
        text = _normalize_newlines(block.content)
        for para in re.split(r"\n+", text):
            para = para.strip()
            if para:
                result.append(WechatBlock(kind="text", content=para))
    return result


def parse_article_html(raw_html: str, url: str) -> WechatArticle:
    """Extract title, author, body paragraphs and images from an article page.

    Pure function. When the page carries no body (WeChat's share-card/verify
    pages), ``paragraphs`` falls back to the og:description so the message is
    still informative.
    """
    doc = lxml_html.fromstring(raw_html)

    title = _meta_content(doc, "og:title") or ""
    author_nodes = doc.xpath('//*[@id="js_name"]/text()')
    author = (author_nodes[0].strip() if author_nodes else None) or None
    if not author:
        author = _meta_content(doc, "og:article:author") or None
    description = _meta_content(doc, "og:description") or ""

    published_at: datetime | None = None
    time_nodes = doc.xpath('//*[@id="publish_time"]/text()')
    if time_nodes and (t := time_nodes[0].strip()):
        try:
            published_at = datetime.strptime(t, "%Y-%m-%d %H:%M")
        except ValueError:
            published_at = None
    if published_at is None:
        ct_match = re.search(r"var ct = \"?(\d{10})\"?", raw_html)
        if ct_match:
            try:
                published_at = datetime.fromtimestamp(int(ct_match.group(1)))
            except (ValueError, OSError):
                published_at = None

    paragraphs = _paragraphs_from_html(raw_html)
    images = _images_from_html(raw_html)
    blocks = _blocks_from_html(raw_html)
    if not paragraphs and description:
        paragraphs = [_normalize_newlines(description)]
    if not blocks and paragraphs:
        blocks = [WechatBlock(kind="text", content=p) for p in paragraphs]
    return WechatArticle(
        url=url,
        title=title.strip(),
        author=author,
        published_at=published_at,
        paragraphs=paragraphs,
        images=images,
        blocks=blocks,
        description=description,
    )


async def fetch_article(url: str) -> WechatArticle:
    """Fetch and parse one article. Raises on network/parse failure."""
    if not is_wechat_url(url):
        raise ValueError(f"not a wechat article url: {url!r}")
    async with httpx.AsyncClient(
        timeout=_TIMEOUT,
        headers={"User-Agent": _USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"},
        follow_redirects=True,
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return parse_article_html(resp.text, str(resp.url))


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def build_rich_blocks(
    article: WechatArticle,
    lang: str = "zh-CN",
    photo_refs: list[Any] | None = None,
) -> list[Any]:
    """Build structured MTProto rich-message blocks (raw PageBlock list).

    Images are referenced by uploaded photo id (``PageBlockPhoto.photo_id``
    matches an ``InputPhoto`` passed in ``InputRichMessage.photos``), which is
    the native MTProto equivalent of Bot API 10.2 media support — no URL
    fetching involved. ``photo_refs`` maps the article's image blocks in
    order to uploaded ``InputPhoto`` objects; ``None`` drops the image.
    """
    # kurigram does not re-export the new rich-message raw types from the
    # package namespace; import each from its generated module file.
    from pyrogram.raw.types.page_block_blockquote import (
        PageBlockBlockquote as _RBlockquote,
    )
    from pyrogram.raw.types.page_block_divider import PageBlockDivider as _RDivider
    from pyrogram.raw.types.page_block_heading1 import (
        PageBlockHeading1 as _RHeading1,
    )
    from pyrogram.raw.types.page_block_paragraph import (
        PageBlockParagraph as _RParagraph,
    )
    from pyrogram.raw.types.page_block_photo import PageBlockPhoto as _RPhoto
    from pyrogram.raw.types.page_caption import PageCaption as _RCaption
    from pyrogram.raw.types.text_empty import TextEmpty as _REmpty
    from pyrogram.raw.types.text_plain import TextPlain as _RPlain
    from pyrogram.raw.types.text_url import TextUrl as _RUrl

    from kmua import i18n

    def text(value: str) -> Any:
        return _RPlain(text=value)

    blocks: list[Any] = []
    if article.title:
        blocks.append(_RHeading1(text=text(article.title)))
    meta: list[str] = []
    if article.author:
        meta.append(article.author)
    if article.published_at:
        meta.append(article.published_at.strftime("%Y-%m-%d"))
    if meta:
        blocks.append(_RParagraph(text=text("👤 " + " · ".join(meta))))
    blocks.append(_RDivider())

    body = article.blocks or [
        WechatBlock(kind="text", content=p) for p in article.paragraphs
    ]
    image_index = 0
    remaining = _MAX_BODY_CHARS
    quote_buffer: list[str] = []

    def flush_quote() -> None:
        # Consecutive paragraphs share ONE block quote (separated by blank
        # lines inside it) instead of one block per paragraph, so the body
        # reads as a continuous quotation.
        if not quote_buffer:
            return
        blocks.append(
            _RBlockquote(
                text=text("\n\n".join(quote_buffer)),
                caption=_REmpty(),
            )
        )
        quote_buffer.clear()

    for block in body:
        if block.kind == "image":
            ref = (
                photo_refs[image_index]
                if photo_refs and image_index < len(photo_refs)
                else None
            )
            image_index += 1
            flush_quote()
            if ref is None:
                continue
            blocks.append(
                _RPhoto(
                    photo_id=ref.id,
                    caption=_RCaption(text=_REmpty(), credit=_REmpty()),
                )
            )
            continue
        if remaining <= 0:
            break
        chunk = _truncate(block.content, min(_MAX_PARAGRAPH_CHARS, remaining))
        # Normalize inner newlines: a single paragraph may carry several
        # line breaks from the source HTML; collapse runs so the joined
        # quote shows one blank line between paragraphs, not a wall of them.
        chunk = re.sub(r"\n+", "\n", chunk).strip()
        quote_buffer.append(chunk)
        remaining -= len(chunk)
    flush_quote()

    blocks.append(_RDivider())
    blocks.append(
        _RParagraph(
            text=_RUrl(
                url=article.url,
                webpage_id=0,
                text=text(i18n.t("bot.msg.wechat.read_original", locale=lang)),
            )
        )
    )
    return blocks


def build_media_caption(article: WechatArticle, lang: str = "zh-CN") -> str:
    """Short caption for a media group (shown above the images).

    Pure function; Telegram's caption limit is 1024 characters.
    """
    from kmua import i18n

    lines: list[str] = []
    if article.title:
        lines.append(f"<b>{html_mod.escape(article.title)}</b>")
    meta: list[str] = []
    if article.author:
        meta.append(html_mod.escape(article.author))
    if article.published_at:
        meta.append(html_mod.escape(article.published_at.strftime("%Y-%m-%d")))
    if meta:
        lines.append("👤 " + " · ".join(meta))
    if article.paragraphs:
        excerpt = _truncate(article.paragraphs[0], 200)
        lines.append(f"<blockquote>{html_mod.escape(excerpt)}</blockquote>")
    lines.append(
        f'🔗 <a href="{html_mod.escape(article.url)}">'
        f"{html_mod.escape(i18n.t('bot.msg.wechat.read_original', locale=lang))}</a>"
    )
    caption = "\n".join(lines)
    return _truncate(caption, 1024)


def _resize_image(pic_bytes: bytes) -> bytes:
    """Shrink an oversized image to 2560px max, JPEG q90 (Telegram limit)."""
    with Image.open(io.BytesIO(pic_bytes)) as image:
        ratio = 2560 / max(image.width, image.height)
        if ratio < 1:
            image = image.resize(
                (int(image.width * ratio), int(image.height * ratio)),
                Image.Resampling.LANCZOS,
            )
        output = io.BytesIO()
        image.convert("RGB").save(output, format="JPEG", quality=90)
        return output.getvalue()


def _validate_image(data: bytes) -> bytes:
    """Verify an image is Telegram-sendable, always converting to a JPEG.

    Raises ValueError for data PIL cannot fully decode (truncated/corrupt
    files). Every accepted image is re-encoded as an RGB JPEG capped at 2560px
    on the long side: WeChat CDN photos occasionally carry PNG/WebP payloads
    that Telegram's upload path rejects with PHOTO_INVALID_DIMENSIONS, and a
    deterministic re-encode removes format, dimension and corruption variance
    in one step.
    """
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            if width <= 0 or height <= 0:
                raise ValueError(f"invalid image size {width}x{height}")
            # Telegram rejects photos with an aspect ratio beyond 20:1; WeChat
            # decorative strips (e.g. 844x18) hit this and fail the whole
            # media group, so drop them instead.
            if max(width / height, height / width) > 20:
                raise ValueError(f"extreme aspect ratio {width}x{height}")
            image.verify()  # force a full decode; truncated files raise here
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"unreadable image: {e.__class__.__name__}") from e
    return _resize_image(data)


async def download_image(client: httpx.AsyncClient, url: str) -> bytes:
    """Download one article image; raises when it fails or is unusable."""
    if not _is_wechat_image_url(url):
        raise ValueError(f"not a wechat cdn image url: {url!r}")
    resp = await client.get(url)
    resp.raise_for_status()
    data = await resp.aread()
    if len(data) > 10 * 1024 * 1024:
        raise ValueError("image too large")
    return await asyncio.to_thread(_validate_image, data)


__all__ = [
    "WechatArticle",
    "WECHAT_URL_RE",
    "build_media_caption",
    "download_image",
    "fetch_article",
    "is_wechat_url",
    "parse_article_html",
]
