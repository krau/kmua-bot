"""Static hosting and routing tests.

The SPA is mounted as a catch-all at the root, which makes it easy to accidentally
shadow the API: an unknown `/api/*` path returning the app shell with status 200 is a
bug the frontend sees as "JSON.parse failed" rather than "404". These tests pin which
paths fall back to the app shell and which stay 404.
"""

from __future__ import annotations

import os

import pytest

from tests.webapp_helpers import api_client

pytestmark = pytest.mark.usefixtures("initialised_db")


def bundle_present() -> bool:
    from kmua.webapp.static import static_bundle_exists

    return static_bundle_exists()


requires_bundle = pytest.mark.skipif(
    not bundle_present(),
    reason="frontend bundle not built (run `pnpm build` in webapp/)",
)


@requires_bundle
@pytest.mark.parametrize("path", ["/", "/me", "/chats/-100123", "/admin/users"])
async def test_client_routes_serve_the_app_shell(path):
    async with api_client() as client:
        response = await client.get(path)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


@requires_bundle
@pytest.mark.parametrize(
    "path",
    [
        "/api/nope",
        "/api/admin/nope",
        # A missing asset must not become HTML: the browser would report a parse
        # error instead of the real "stale bundle" problem.
        "/assets/missing-abcdef.js",
        "/favicon.ico",
    ],
)
async def test_server_paths_and_assets_do_not_fall_back(path):
    async with api_client() as client:
        response = await client.get(path)

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


@requires_bundle
async def test_an_unauthenticated_api_route_still_answers_401():
    """The catch-all must not swallow a real endpoint and turn 401 into the shell."""
    async with api_client() as client:
        response = await client.get("/api/me")

    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_MISSING"


@requires_bundle
async def test_the_app_shell_is_not_cached():
    """index.html must revalidate, or clients keep booting a deleted bundle."""
    async with api_client() as client:
        response = await client.get("/")

    assert "no-cache" in response.headers["cache-control"]
    assert "frame-ancestors" in response.headers["content-security-policy"]


@requires_bundle
async def test_hashed_assets_are_cached_immutably():
    from kmua.webapp.static import resolve_static_dir

    asset = next(
        name for name in os.listdir(resolve_static_dir() / "assets") if name.endswith(".js")
    )

    async with api_client() as client:
        response = await client.get(f"/assets/{asset}")

    assert response.status_code == 200
    assert "immutable" in response.headers["cache-control"]


async def test_health_endpoints_work_with_the_panel_disabled():
    """Turning the panel off must not break the container health check."""
    import httpx

    from kmua.webapp import create_app

    app = create_app(panel_enabled=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://panel.test") as client:
        health = await client.get("/health")
        ready = await client.get("/ready")
        panel = await client.get("/api/me")

    # 503 because no bot client is connected in tests; the point is that the route
    # exists and answers with the documented body.
    assert health.status_code == 503
    assert health.json()["bot_connected"] is False
    assert ready.status_code == 503
    # No management surface is mounted at all.
    assert panel.status_code == 404
