"""Size-capped HTTP downloads.

Several features used to pull whole media files into memory with ``aread()``
and validate the size afterwards. A single large video then meant hundreds of
megabytes of allocations, GC pressure and swap thrash inside the bot process -
visible as event-loop stalls of tens of seconds. These helpers enforce the cap
from the response headers up front and abort the body stream as soon as the
running total exceeds it.
"""

from __future__ import annotations

import httpx

_CHUNK = 64 * 1024


class DownloadTooLargeError(ValueError):
    """The response exceeds the configured byte cap."""


async def download_capped(
    client: httpx.AsyncClient,
    url: str,
    max_bytes: int,
    *,
    timeout: httpx.Timeout | float | None = None,
) -> bytes:
    """GET *url* and return at most *max_bytes* body bytes.

    Raises :class:`DownloadTooLargeError` (a ValueError) when the declared or
    actual body size exceeds the cap; the connection is closed instead of
    downloading the remainder.
    """
    async with client.stream("GET", url, timeout=timeout) as resp:
        resp.raise_for_status()
        declared = resp.headers.get("Content-Length")
        if declared is not None and declared.isdigit() and int(declared) > max_bytes:
            raise DownloadTooLargeError(
                f"{url}: response is {declared} bytes, cap is {max_bytes}"
            )
        chunks: list[bytes] = []
        total = 0
        async for chunk in resp.aiter_bytes(_CHUNK):
            total += len(chunk)
            if total > max_bytes:
                raise DownloadTooLargeError(
                    f"{url}: response exceeds {max_bytes} bytes"
                )
            chunks.append(chunk)
        return b"".join(chunks)


__all__ = ["DownloadTooLargeError", "download_capped"]
