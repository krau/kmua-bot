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
    - **bold** or __bold__ -> <b>bold</b>
    - *italic* or _italic_ -> <i>italic</i>
    - __underline__ -> <u>underline</u>
    - ~~strikethrough~~ -> <s>strikethrough</s>
    - ||spoiler|| -> <tg-spoiler>spoiler</tg-spoiler>
    - [link](url) -> <a href="url">link</a>
    - `inline code` -> <code>inline code</code>
    - ```code block``` or ```lang\ncode``` -> <pre> or <pre><code class="language-lang">
    - > quote -> <blockquote>quote</blockquote>
    - >> expandable quote -> <blockquote expandable>quote</blockquote>

    Returns:
        Telegram HTML formatted text.
    """
    if not text:
        return ""

    # Store code blocks and inline code to protect them from markdown parsing
    code_blocks: list[str] = []
    inline_codes: list[str] = []

    def store_code_block(match: re.Match) -> str:
        code_blocks.append(match.group(0))
        return f"\x00CODEBLOCK{len(code_blocks) - 1}\x00"

    def store_inline_code(match: re.Match) -> str:
        inline_codes.append(match.group(0))
        return f"\x00INLINECODE{len(inline_codes) - 1}\x00"

    # Protect code blocks (```...```)
    text = re.sub(r"```(\w+)?\n(.*?)```", store_code_block, text, flags=re.DOTALL)

    # Protect inline code (`...`)
    text = re.sub(r"`([^`]+)`", store_inline_code, text)

    # Process blockquotes first (must be at line start)
    lines = text.split("\n")
    result_lines = []
    in_quote = False
    in_expandable = False
    quote_lines = []

    for line in lines:
        # Check for expandable quote (>>)
        if line.startswith(">> "):
            if not in_quote:
                in_quote = True
                in_expandable = True
                quote_lines = [line[3:]]
            else:
                quote_lines.append(line[3:])
        # Check for regular quote (>)
        elif line.startswith("> "):
            if not in_quote:
                in_quote = True
                in_expandable = False
                quote_lines = [line[2:]]
            else:
                quote_lines.append(line[2:])
        else:
            if in_quote:
                # Close the quote block
                quote_content = "\n".join(quote_lines)
                quote_content = _escape_html(quote_content)
                if in_expandable:
                    result_lines.append(
                        f"<blockquote expandable>{quote_content}</blockquote>"
                    )
                else:
                    result_lines.append(f"<blockquote>{quote_content}</blockquote>")
                in_quote = False
                in_expandable = False
                quote_lines = []
            result_lines.append(line)

    # Close any remaining quote block
    if in_quote:
        quote_content = "\n".join(quote_lines)
        quote_content = _escape_html(quote_content)
        if in_expandable:
            result_lines.append(f"<blockquote expandable>{quote_content}</blockquote>")
        else:
            result_lines.append(f"<blockquote>{quote_content}</blockquote>")

    text = "\n".join(result_lines)

    # Process spoilers (||text||) - must be before other patterns
    text = re.sub(
        r"\|\|([^|]+)\|\|",
        lambda m: f"<tg-spoiler>{_escape_html(m.group(1))}</tg-spoiler>",
        text,
    )

    # Process strikethrough (~~text~~)
    text = re.sub(r"~~([^~]+)~~", lambda m: f"<s>{_escape_html(m.group(1))}</s>", text)

    # Process bold (**text** or __text__)
    # Must be before italic to avoid conflicts
    text = re.sub(
        r"\*\*([^*]+)\*\*", lambda m: f"<b>{_escape_html(m.group(1))}</b>", text
    )
    text = re.sub(r"__([^_]+)__", lambda m: f"<b>{_escape_html(m.group(1))}</b>", text)

    # Process underline (__text__) - only if not already processed as bold
    # Actually, Telegram uses <u> for underline, let's use different pattern
    # Using ++text++ for underline to avoid conflict
    text = re.sub(
        r"\+\+([^+]+)\+\+", lambda m: f"<u>{_escape_html(m.group(1))}</u>", text
    )

    # Process italic (*text* or _text_)
    # Must be after bold
    text = re.sub(
        r"(?<!\*)\*(?!\*)([^*]+)(?<!\*)\*(?!\*)",
        lambda m: f"<i>{_escape_html(m.group(1))}</i>",
        text,
    )
    text = re.sub(
        r"(?<!_)_(?!_)([^_]+)(?<!_)_(?!_)",
        lambda m: f"<i>{_escape_html(m.group(1))}</i>",
        text,
    )

    # Process links [text](url)
    def process_link(match: re.Match) -> str:
        link_text = match.group(1)
        url = match.group(2)
        # Escape link text
        link_text = _escape_html(link_text)
        return f'<a href="{url}">{link_text}</a>'

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", process_link, text)

    # Restore inline code
    for i, code in enumerate(inline_codes):
        # Extract content without backticks
        content = code[1:-1]
        # Escape HTML in code
        content = _escape_html(content)
        text = text.replace(f"\x00INLINECODE{i}\x00", f"<code>{content}</code>")

    # Restore code blocks
    for i, code in enumerate(code_blocks):
        match = re.match(r"```(\w+)?\n(.*?)```", code, re.DOTALL)
        if match:
            lang = match.group(1) or ""
            content = match.group(2)
            # Escape HTML in code
            content = _escape_html(content)
            if lang:
                text = text.replace(
                    f"\x00CODEBLOCK{i}\x00",
                    f'<pre><code class="language-{lang}">{content}</code></pre>',
                )
            else:
                text = text.replace(f"\x00CODEBLOCK{i}\x00", f"<pre>{content}</pre>")

    # Escape remaining HTML characters in plain text parts
    # Split by HTML tags and escape only text parts
    parts = re.split(r"(<[^>]+>)", text)
    result = []
    for i, part in enumerate(parts):
        if i % 2 == 0:  # Text part (not a tag)
            result.append(_escape_html(part))
        else:  # HTML tag
            result.append(part)

    return "".join(result)


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
