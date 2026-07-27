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
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            {"status": "error", "error": str(e)},
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
        return JSONResponse(
            {"status": "error", "error": str(e)},
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
