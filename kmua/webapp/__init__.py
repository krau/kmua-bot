"""The FastAPI application factory.

One app serves three things on one port: the health endpoints, the JSON API, and
the built frontend. Keeping them together means a single listener to configure,
one TLS terminator in front, and no CORS in production.

Route order matters: the SPA is mounted at "/" and swallows everything, so it is
mounted last, after every API router.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from kmua.config import app_config
from kmua.logger import logger
from kmua.webapp.errors import install_error_handlers
from kmua.webapp.routers import system
from kmua.webapp.static import add_api_security_headers, mount_static

__all__ = ["create_app"]


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.debug("webapp: application started")
    yield
    logger.debug("webapp: application stopped")


def create_app(*, panel_enabled: bool | None = None) -> FastAPI:
    """Build the ASGI app.

    When the panel is disabled only the health endpoints are mounted, so
    container health checks keep working without exposing any management surface.
    """
    enabled = app_config.webapp if panel_enabled is None else panel_enabled

    app = FastAPI(
        title="kmua panel",
        version="1",
        lifespan=_lifespan,
        # The panel is the only consumer and it is typed by hand; a public schema
        # endpoint would just be extra surface.
        docs_url="/api/docs" if app_config.debug else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if app_config.debug else None,
    )

    install_error_handlers(app)
    app.add_middleware(BaseHTTPMiddleware, dispatch=add_api_security_headers)

    app.include_router(system.router)

    if not enabled:
        logger.info("webapp: panel disabled, serving health endpoints only")
        return app

    if app_config.webapp_allow_origins:
        # Development only: the production build is served same-origin.
        logger.warning(
            "webapp: CORS enabled for "
            f"{app_config.webapp_allow_origins} - do not use this in production"
        )
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(app_config.webapp_allow_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
        )

    from kmua.webapp.routers import admin, auth, chats, me

    app.include_router(auth.router)
    app.include_router(me.router)
    app.include_router(chats.router)
    app.include_router(admin.router)

    # Mounted last: this catch-all must not shadow the API routes.
    mount_static(app)

    return app
