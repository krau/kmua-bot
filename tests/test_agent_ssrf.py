"""SSRF guard: safe_http validation, web fetching and tg media download."""

from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

import httpx
import pytest

from kmua.common import safe_http
from kmua.common.safe_http import UnsafeUrlError, is_safe_web_url, safe_download_bytes
from kmua.plugins.agent.tools import tg_ops


def test_is_safe_web_url():
    assert is_safe_web_url("https://1.1.1.1/x")
    assert is_safe_web_url("https://8.8.8.8/x")
    assert not is_safe_web_url("http://127.0.0.1/x")
    assert not is_safe_web_url("http://localhost/x")
    assert not is_safe_web_url("http://10.0.0.5/x")
    assert not is_safe_web_url("http://192.168.1.1/x")
    assert not is_safe_web_url("http://169.254.169.254/latest/meta-data/")
    assert not is_safe_web_url("http://[::1]/x")
    assert not is_safe_web_url("http://mybox.local/x")
    assert not is_safe_web_url("ftp://example.com/x")
    assert not is_safe_web_url("not a url")
    assert not is_safe_web_url("http://definitely-not-a-real-host-zzz.invalid/x")


async def test_safe_download_rejects_private_redirect(monkeypatch):
    """A redirect to a private address must be refused, not followed."""

    class FakeResponse:
        status_code = 302
        headers = {"location": "http://169.254.169.254/latest/meta-data/"}
        request = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def aiter_bytes(self):
            yield b""

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def stream(self, method, url, timeout=None):
            assert method == "GET"
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FakeClient())
    with pytest.raises(UnsafeUrlError):
        await safe_download_bytes("https://example.com/redirect")


async def test_safe_download_size_limit(monkeypatch):
    class FakeResponse:
        status_code = 200
        request = None
        headers = {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def aiter_bytes(self):
            yield b"a" * 100

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def stream(self, method, url, timeout=None):
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FakeClient())
    monkeypatch.setattr(safe_http, "is_safe_web_url", lambda url: True)
    with pytest.raises(httpx.HTTPError):
        await safe_download_bytes("https://example.com/big", max_bytes=50)


def _ctx(client=None):
    return SimpleNamespace(
        deps=SimpleNamespace(
            client=client or SimpleNamespace(),
            chat_id=-100_123,
            user_id=1001,
            message=SimpleNamespace(id=7, guest_query_id=None),
            is_guest_mode=False,
        )
    )


async def test_tg_media_url_downloaded_safely(monkeypatch):
    calls = {}

    async def fake_download(url, max_bytes=None):
        calls["url"] = url
        return b"fake-image-bytes"

    monkeypatch.setattr(tg_ops, "safe_download_bytes", fake_download)

    async def fake_send_photo(chat_id, **kwargs):
        calls["sent"] = kwargs["photo"]
        return SimpleNamespace(message_id=1)

    await tg_ops.tg(
        _ctx(SimpleNamespace(send_photo=fake_send_photo)),
        "sendPhoto",
        {"photo": "https://example.com/img.png", "caption": "hi"},
    )
    assert calls["url"] == "https://example.com/img.png"
    assert isinstance(calls["sent"], BytesIO)
    assert calls["sent"].read() == b"fake-image-bytes"
    assert calls["sent"].name == "img.png"  # pyrogram needs .name on in-memory files


async def test_tg_media_unsafe_url_rejected(monkeypatch):
    async def fake_send_photo(chat_id, **kwargs):
        raise AssertionError("should not be called")

    result = await tg_ops.tg(
        _ctx(SimpleNamespace(send_photo=fake_send_photo)),
        "sendPhoto",
        {"photo": "http://127.0.0.1/img.png"},
    )
    assert "not a public internet address" in result or "Error" in result


async def test_tg_media_file_id_passed_through(monkeypatch):
    calls = {}

    async def fake_send_document(chat_id, **kwargs):
        calls["document"] = kwargs["document"]
        return SimpleNamespace(message_id=1)

    await tg_ops.tg(
        _ctx(SimpleNamespace(send_document=fake_send_document)),
        "sendDocument",
        {"document": "AgACAgUAAxUAAW3"},
    )
    assert calls["document"] == "AgACAgUAAxUAAW3"


async def test_send_contact_removed():
    result = await tg_ops.tg(
        _ctx(), "sendContact", {"phone_number": "123", "first_name": "x"}
    )
    assert "Unknown method" in result


async def test_send_location_removed():
    result = await tg_ops.tg(
        _ctx(), "sendLocation", {"latitude": 1.0, "longitude": 2.0}
    )
    assert "Unknown method" in result


async def test_tg_media_name_inferred_from_url(monkeypatch):
    """sendDocument URL download must carry a filename so pyrogram can send it."""
    calls = {}

    async def fake_download(url, max_bytes=None):
        return b"doc-bytes"

    monkeypatch.setattr(tg_ops, "safe_download_bytes", fake_download)

    async def fake_send_document(chat_id, **kwargs):
        calls["document"] = kwargs["document"]
        return SimpleNamespace(message_id=1)

    await tg_ops.tg(
        _ctx(SimpleNamespace(send_document=fake_send_document)),
        "sendDocument",
        {"document": "https://cdn.example.com/report.pdf"},
    )
    assert isinstance(calls["document"], BytesIO)
    assert calls["document"].name == "report.pdf"


async def test_tg_media_name_default_ext_when_missing(monkeypatch):
    """URLs without a recognizable extension get the method's default one."""
    calls = {}

    async def fake_download(url, max_bytes=None):
        return b"audio-bytes"

    monkeypatch.setattr(tg_ops, "safe_download_bytes", fake_download)

    async def fake_send_audio(chat_id, **kwargs):
        calls["audio"] = kwargs["audio"]
        return SimpleNamespace(message_id=1)

    await tg_ops.tg(
        _ctx(SimpleNamespace(send_audio=fake_send_audio)),
        "sendAudio",
        {"audio": "https://cdn.example.com/stream"},
    )
    assert calls["audio"].name == "stream.mp3"


async def test_tg_media_file_id_still_passthrough():
    calls = {}

    async def fake_send_video(chat_id, **kwargs):
        calls["video"] = kwargs["video"]
        return SimpleNamespace(message_id=1)

    await tg_ops.tg(
        _ctx(SimpleNamespace(send_video=fake_send_video)),
        "sendVideo",
        {"video": "BAACAgUAAxUAAW3"},
    )
    assert calls["video"] == "BAACAgUAAxUAAW3"


async def test_safe_download_content_length_precheck(monkeypatch):
    """A declared Content-Length over the cap is refused before any body
    byte is read."""
    body_read = []

    class FakeResponse:
        status_code = 200
        request = None
        headers = {"content-length": "100000"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def aiter_bytes(self):
            body_read.append(True)
            yield b"x"

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def stream(self, method, url, timeout=None):
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FakeClient())
    monkeypatch.setattr(safe_http, "is_safe_web_url", lambda url: True)
    with pytest.raises(httpx.HTTPError):
        await safe_download_bytes("https://example.com/big", max_bytes=50)
    assert body_read == [], "the body must not be read at all"


async def test_safe_download_under_declared_length_streams(monkeypatch):
    """A declared length within the cap still streams; the streaming count
    is the second layer when the server under-declares."""

    class FakeResponse:
        status_code = 200
        request = None
        headers = {"content-length": "10"}  # lies: the body is 100 bytes

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def aiter_bytes(self):
            yield b"a" * 100

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def stream(self, method, url, timeout=None):
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FakeClient())
    monkeypatch.setattr(safe_http, "is_safe_web_url", lambda url: True)
    with pytest.raises(httpx.HTTPError):
        await safe_download_bytes("https://example.com/under", max_bytes=50)


async def test_safe_download_malformed_content_length(monkeypatch):
    """A malformed Content-Length must not crash; the streaming count
    applies instead."""

    class FakeResponse:
        status_code = 200
        request = None
        headers = {"content-length": "not-a-number"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def aiter_bytes(self):
            yield b"a" * 100

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def stream(self, method, url, timeout=None):
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FakeClient())
    monkeypatch.setattr(safe_http, "is_safe_web_url", lambda url: True)
    with pytest.raises(httpx.HTTPError):
        await safe_download_bytes("https://example.com/bad", max_bytes=50)
