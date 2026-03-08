"""Markdown to Telegram HTML converter.

Converts Markdown format to Telegram's HTML parse mode with fallback to plain text.
Supports Telegram HTML entities: bold, italic, underline, strikethrough, spoiler,
links, inline code, code blocks, and blockquotes.
"""

import re


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def md_to_telegram_html(text: str) -> str:
    """Convert Markdown to Telegram HTML.

    Supported Markdown:
    - # Heading -> <b>Heading</b>
    - **bold** or __bold__ -> <b>bold</b>
    - *italic* or _italic_ -> <i>italic</i>
    - ~~strikethrough~~ -> <s>strikethrough</s>
    - `inline code` -> <code>inline code</code>
    - ```code block``` or ```lang\ncode``` -> <pre> or <pre><code class="language-lang">
    - [link](url) -> <a href="url">link</a>
    - > quote -> <blockquote>quote</blockquote>
    - - item / * item / + item -> • item
    - 1. item -> 1. item
    - --- / *** -> ——————
    - bare URLs -> <a href="url">url</a>

    Returns:
        Telegram HTML formatted text.
    """
    if not text:
        return ""

    lines = text.split("\n")
    result = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Fenced code block
        if line.startswith("```"):
            lang = line[3:].strip()
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # consume closing ```
            code = "\n".join(code_lines)
            if lang:
                result.append(
                    f'<pre><code class="language-{_escape_html(lang)}">{_escape_html(code)}</code></pre>'
                )
            else:
                result.append(f"<pre>{_escape_html(code)}</pre>")
            continue

        # Heading
        if line.startswith("#"):
            level = 0
            while level < len(line) and line[level] == "#":
                level += 1
            heading_text = line[level:].strip()
            result.append(f"<b>{_render_inline(heading_text)}</b>")
            i += 1
            continue

        # Horizontal rule
        stripped = line.strip()
        if _is_horizontal_rule(stripped):
            result.append("——————")
            i += 1
            continue

        # Blockquote
        if line.startswith(">"):
            bq_lines = []
            while i < len(lines) and lines[i].startswith(">"):
                bq_lines.append(lines[i][1:].lstrip())
                i += 1
            inner = md_to_telegram_html("\n".join(bq_lines))
            result.append(f"<blockquote>{inner}</blockquote>")
            continue

        # Unordered list item
        if len(stripped) >= 2 and stripped[0] in "-*+" and stripped[1] == " ":
            text = stripped[2:].strip()
            result.append(f"• {_render_inline(text)}")
            i += 1
            continue

        # Ordered list item
        m = re.match(r"^(\d+)\.\s+(.+)$", stripped)
        if m:
            num = m.group(1)
            text = m.group(2)
            result.append(f"{_escape_html(num)}. {_render_inline(text)}")
            i += 1
            continue

        # Blank line
        if not stripped:
            result.append("")
            i += 1
            continue

        # Paragraph / inline
        result.append(_render_inline(line))
        i += 1

    return "\n".join(result).rstrip("\n")


def _render_inline(s: str) -> str:
    """Convert inline Markdown markup to Telegram HTML."""
    result = []
    pos = 0

    while pos < len(s):
        # Inline code
        if s[pos] == "`":
            end = s.find("`", pos + 1)
            if end >= 0:
                code = s[pos + 1 : end]
                result.append(f"<code>{_escape_html(code)}</code>")
                pos = end + 1
                continue

        # Bold: **text**
        if pos + 1 < len(s) and s[pos : pos + 2] == "**":
            end = s.find("**", pos + 2)
            if end >= 0:
                inner = s[pos + 2 : end]
                result.append(f"<b>{_render_inline(inner)}</b>")
                pos = end + 2
                continue

        # Bold: __text__
        if pos + 1 < len(s) and s[pos : pos + 2] == "__":
            end = s.find("__", pos + 2)
            if end >= 0:
                inner = s[pos + 2 : end]
                result.append(f"<b>{_render_inline(inner)}</b>")
                pos = end + 2
                continue

        # Italic: *text*
        if s[pos] == "*":
            end = s.find("*", pos + 1)
            if end >= 0:
                inner = s[pos + 1 : end]
                result.append(f"<i>{_render_inline(inner)}</i>")
                pos = end + 1
                continue

        # Italic: _text_
        if s[pos] == "_":
            end = s.find("_", pos + 1)
            if end >= 0:
                inner = s[pos + 1 : end]
                result.append(f"<i>{_render_inline(inner)}</i>")
                pos = end + 1
                continue

        # Strikethrough: ~~text~~
        if pos + 1 < len(s) and s[pos : pos + 2] == "~~":
            end = s.find("~~", pos + 2)
            if end >= 0:
                inner = s[pos + 2 : end]
                result.append(f"<s>{_render_inline(inner)}</s>")
                pos = end + 2
                continue

        # Hyperlink: [text](url)
        if s[pos] == "[":
            m = re.match(r"^\[([^\]]*)\]\(([^)]*)\)", s[pos:])
            if m:
                link_text = m.group(1)
                href = m.group(2)
                result.append(
                    f'<a href="{_escape_html(href)}">{_render_inline(link_text)}</a>'
                )
                pos += len(m.group(0))
                continue

        # Auto-link bare URLs
        if s[pos : pos + 7] == "http://" or s[pos : pos + 8] == "https://":
            end = _url_end(s, pos)
            url = s[pos:end]
            result.append(f'<a href="{_escape_html(url)}">{_escape_html(url)}</a>')
            pos = end
            continue

        # Special HTML chars
        ch = s[pos]
        if ch == "&":
            result.append("&amp;")
        elif ch == "<":
            result.append("&lt;")
        elif ch == ">":
            result.append("&gt;")
        else:
            result.append(ch)
        pos += 1

    return "".join(result)


def _is_horizontal_rule(s: str) -> bool:
    """Check if line is a horizontal rule (---, ***, ___)."""
    if len(s) < 3:
        return False
    ch = s[0]
    if ch not in "-*_":
        return False
    for c in s:
        if c != ch and c != " ":
            return False
    return True


def _url_end(s: str, pos: int) -> int:
    """Find the end of a URL starting at pos."""
    i = pos
    while i < len(s):
        c = s[i]
        if c in " \t\n\r":
            break
        # Strip trailing punctuation
        if i > pos and c in ".,)]":
            if i + 1 >= len(s) or s[i + 1] in " \n\t":
                break
        i += 1
    return i


def safe_md_to_telegram_html(text: str) -> tuple[str, bool]:
    """Convert Markdown to Telegram HTML with fallback.

    Returns:
        Tuple of (html_text, success). If conversion fails, returns original text with success=False.
    """
    try:
        html = md_to_telegram_html(text)
        # Basic validation: check for unmatched tags
        # Remove self-closing tags and void elements for counting
        clean = re.sub(r"<[^>]+/>", "", html)  # Self-closing
        clean = re.sub(
            r"<(br|hr|img|input|meta|link)[^>]*>", "", clean, flags=re.I
        )  # Void elements

        # Count opening and closing tags (excluding attributes)
        open_tags = re.findall(r"<([a-zA-Z][a-zA-Z0-9-]*)[^>]*>", clean)
        close_tags = re.findall(r"</([a-zA-Z][a-zA-Z0-9-]*)>", clean)

        # Simple check: opening and closing counts should match
        from collections import Counter

        open_counts = Counter(t.lower() for t in open_tags)
        close_counts = Counter(t.lower() for t in close_tags)

        # Check if counts match for standard tags
        for tag in ["b", "i", "u", "s", "code", "pre", "a", "blockquote", "tg-spoiler"]:
            if open_counts[tag] != close_counts[tag]:
                # Unmatched tags, return original
                return text, False

        return html, True
    except Exception as e:
        logger = __import__("kmua.logger", fromlist=["logger"]).logger
        logger.debug(f"Markdown to HTML conversion failed: {e}")
        return text, False
