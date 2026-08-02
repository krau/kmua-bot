"""Safe outbound HTTP: SSRF guard plus size-limited, redirect-checked fetching.

Every outbound request made on behalf of the agent (web fetching, media
downloads) goes through here. URLs whose host resolves to a non-global IP
(loopback, private, link-local, metadata ranges), localhost or .local names
are rejected, and redirects are re-checked hop by hop.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx

MAX_REDIRECTS = 5
DEFAULT_MAX_BYTES = 20 * 1024 * 1024  # 20 MB


def is_safe_web_url(url: str) -> bool:
    """Return True when the URL's host is a public internet host.

    Rejects: non-http(s) schemes, missing host, localhost, *.local names,
    hosts that fail DNS resolution, and hosts resolving to any non-global IP.
    """
    if not url.startswith(("http://", "https://")):
        return False
    host = urlparse(url).hostname
    if not host:
        return False
    lowered = host.lower().rstrip(".")
    if lowered == "localhost" or lowered.endswith(".local"):
        return False
    try:
        ip = ipaddress.ip_address(lowered)
    except ValueError:
        ip = None
    if ip is not None:
        return ip.is_global
    try:
        infos = socket.getaddrinfo(lowered, None)
    except socket.gaierror:
        return False
    for info in infos:
        addr = ipaddress.ip_address(str(info[4][0]).split("%")[0])
        if not addr.is_global:
            return False
    return True


class UnsafeUrlError(ValueError):
    """Raised when a URL fails the SSRF guard."""


async def safe_download_bytes(
    url: str,
    max_bytes: int = DEFAULT_MAX_BYTES,
    timeout: float = 30.0,
) -> bytes:
    """Download *url* with the SSRF guard applied to every redirect hop.

    Raises UnsafeUrlError for unsafe URLs and httpx errors otherwise.
    """
    current = url
    async with httpx.AsyncClient(follow_redirects=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            if not is_safe_web_url(current):
                raise UnsafeUrlError(f"Unsafe URL: {current}")
            async with client.stream("GET", current, timeout=timeout) as resp:
                if resp.status_code in (301, 302, 303, 307, 308):
                    location = resp.headers.get("location")
                    if not location:
                        raise httpx.HTTPError(f"Redirect without Location: {current}")
                    current = urljoin(current, location)
                    continue
                if resp.status_code != 200:
                    raise httpx.HTTPStatusError(
                        f"GET {current} -> {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )
                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise httpx.HTTPError(
                            f"Content exceeds {max_bytes} bytes: {current}"
                        )
                    chunks.append(chunk)
                return b"".join(chunks)
    raise httpx.HTTPError(f"Too many redirects: {url}")


async def safe_fetch_text(
    url: str,
    max_bytes: int = DEFAULT_MAX_BYTES,
    timeout: float = 30.0,
) -> str:
    """Fetch *url* and return its text content (HTML stripped to text)."""
    raw = await safe_download_bytes(url, max_bytes=max_bytes, timeout=timeout)
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(raw, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "aside"]):
            tag.decompose()
        text = soup.get_text("\n", strip=True)
        return text
    except Exception:
        return raw.decode("utf-8", errors="replace")
