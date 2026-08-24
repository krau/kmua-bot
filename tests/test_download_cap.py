"""Size-capped media downloads (kmua.common.download)."""

from __future__ import annotations

import httpx
import pytest

from kmua.common.download import DownloadTooLargeError, download_capped


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_returns_body_under_cap():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"hello")

    async with _client(handler) as client:
        assert await download_capped(client, "https://x/y", 10) == b"hello"


async def test_rejects_declared_content_length_without_downloading():

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"Content-Length": "1000"}, content=b"x" * 1000
        )

    async with _client(handler) as client:
        with pytest.raises(DownloadTooLargeError):
            await download_capped(client, "https://x/big", 10)


async def test_aborts_stream_past_cap():
    async def handler(request: httpx.Request) -> httpx.Response:
        # No Content-Length header: the cap must be enforced while streaming.
        return httpx.Response(200, content=b"y" * 100)

    async with _client(handler) as client:
        with pytest.raises(DownloadTooLargeError):
            await download_capped(client, "https://x/stream", 10)


async def test_http_error_propagates():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    async with _client(handler) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await download_capped(client, "https://x/missing", 10)
