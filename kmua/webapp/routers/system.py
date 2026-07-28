"""Health, readiness and version endpoints.

These replace the standalone aiohttp server that used to live in `kmua/health.py`.
Paths, response bodies and status codes are unchanged so existing container health
checks keep working, and they stay mounted even when the panel is disabled.
"""

from fastapi import APIRouter, Response, status
from fastapi.responses import JSONResponse

from kmua.bot.client import client
from kmua.config import app_config
from kmua.logger import logger

router = APIRouter(tags=["system"])

# What an unauthenticated caller is told when the check itself raised. The field is
# kept rather than dropped so the response shape does not change with the failure
# mode, but its value is fixed: see the handlers for why.
_OPAQUE_ERROR = "Health check failed"


@router.get("/health", include_in_schema=False)
async def health_check() -> Response:
    """Report whether the bot client is connected.

    Returns 200 when connected, 503 otherwise, so orchestrators can restart a
    container whose Telegram session died.
    """
    try:
        if client.is_connected:
            return JSONResponse(
                {
                    "status": "healthy",
                    "bot_connected": True,
                    "bot_id": client.me.id if client.me else None,
                },
                status_code=status.HTTP_200_OK,
            )
        return JSONResponse(
            {
                "status": "unhealthy",
                "bot_connected": False,
                "error": "Bot client not connected",
            },
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except Exception as e:
        # The exception text stays in the log, not in the response. These two routes
        # are unauthenticated by design - a container health check cannot present a
        # token - so anything they return is public, and an exception string can
        # carry a stack frame, a path or a hostname. The operator reading the log has
        # the detail; the caller only needs the verdict.
        logger.opt(exception=e).error("webapp: health check failed")
        return JSONResponse(
            {
                "status": "error",
                "bot_connected": False,
                "error": _OPAQUE_ERROR,
            },
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


@router.get("/ready", include_in_schema=False)
async def readiness_check() -> Response:
    """Report whether the bot finished initialising and can serve traffic."""
    try:
        if client.is_connected and client.me:
            return JSONResponse(
                {
                    "status": "ready",
                    "bot_username": client.me.username,
                    "bot_id": client.me.id,
                },
                status_code=status.HTTP_200_OK,
            )
        return JSONResponse(
            {"status": "not_ready"},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except Exception as e:
        # Same reasoning as /health: log the detail, return only the verdict.
        logger.opt(exception=e).error("webapp: readiness check failed")
        return JSONResponse(
            {"status": "error", "error": _OPAQUE_ERROR},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


@router.get("/api/system/info")
async def system_info() -> dict[str, object]:
    """Public metadata the frontend needs before authenticating."""
    return {
        "bot_username": client.me.username if client.me else None,
        "panel_enabled": app_config.webapp,
        "available_locales": sorted(_available_locales()),
    }


def _available_locales() -> list[str]:
    from kmua.i18n import i18n

    return i18n.get_available_locales()
