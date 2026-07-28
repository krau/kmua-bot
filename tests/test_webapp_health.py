"""Health and readiness endpoint tests.

These two routes are unauthenticated by necessity - a container health check cannot
present a token - so whatever they return is public. That makes their failure path a
disclosure surface: CodeQL flagged `str(e)` reaching the response body, which can carry
a stack frame, a filesystem path or an internal hostname.

The tests below pin that the detail goes to the log and only a verdict goes to the
caller, and that the happy paths still answer with the documented shape, since existing
container health checks parse them.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

pytestmark = pytest.mark.usefixtures("initialised_db")


async def _get(path: str) -> httpx.Response:
    from kmua.webapp import create_app

    app = create_app(panel_enabled=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://panel.test"
    ) as client:
        return await client.get(path)


class _RaisingClient:
    """Stands in for the bot client when reading its state raises.

    `is_connected` is an instance attribute on pyrogram's Client, so it cannot be
    patched on the class - the whole object is replaced instead.
    """

    def __init__(self, message: str) -> None:
        self._message = message

    @property
    def is_connected(self) -> bool:
        raise RuntimeError(self._message)

    @property
    def me(self):
        raise RuntimeError(self._message)


def _raising_client(message: str):
    """Make reading the client's state raise, as a dead session could."""
    from kmua.webapp.routers import system

    return patch.object(system, "client", _RaisingClient(message))


async def test_health_reports_a_disconnected_client():
    response = await _get("/health")

    assert response.status_code == 503
    assert response.json()["bot_connected"] is False


async def test_ready_reports_not_ready_without_a_client():
    response = await _get("/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


async def test_health_does_not_leak_the_exception_text():
    secret = "/srv/kmua/internal/path.py line 42 in _connect"

    with _raising_client(secret):
        response = await _get("/health")

    assert response.status_code == 503
    body = response.text
    assert secret not in body
    assert "RuntimeError" not in body
    assert response.json()["error"] == "Health check failed"


async def test_ready_does_not_leak_the_exception_text():
    secret = "postgres://kmua:hunter2@db.internal:5432"

    with _raising_client(secret):
        response = await _get("/ready")

    assert response.status_code == 503
    assert secret not in response.text
    assert response.json()["error"] == "Health check failed"


async def test_health_keeps_its_response_shape_when_the_check_raises():
    """Orchestrators parse these fields, so a failure must not change the schema."""
    with _raising_client("boom"):
        response = await _get("/health")

    body = response.json()

    assert set(body) == {"status", "bot_connected", "error"}
    assert body["status"] == "error"
    assert body["bot_connected"] is False
