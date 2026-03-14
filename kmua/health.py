"""Health check HTTP server for Docker container monitoring."""

from aiohttp import web

from kmua.bot.client import client
from kmua.logger import logger

routes = web.RouteTableDef()


@routes.get("/health")
async def health_check(request: web.Request) -> web.Response:
    """Health check endpoint for Docker/container orchestration.

    Returns 200 OK if the bot client is connected and ready,
    otherwise returns 503 Service Unavailable.
    """
    try:
        # Check if client is initialized and connected
        if client.is_connected:
            return web.json_response(
                {
                    "status": "healthy",
                    "bot_connected": True,
                    "bot_id": client.me.id if client.me else None,
                },
                status=200,
            )
        else:
            return web.json_response(
                {
                    "status": "unhealthy",
                    "bot_connected": False,
                    "error": "Bot client not connected",
                },
                status=503,
            )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return web.json_response(
            {
                "status": "error",
                "error": str(e),
            },
            status=503,
        )


@routes.get("/ready")
async def readiness_check(request: web.Request) -> web.Response:
    """Readiness probe for Kubernetes/Docker.

    Returns 200 when the bot is fully initialized and ready to accept traffic.
    """
    try:
        if client.is_connected and client.me:
            return web.json_response(
                {
                    "status": "ready",
                    "bot_username": client.me.username,
                    "bot_id": client.me.id,
                },
                status=200,
            )
        return web.json_response(
            {"status": "not_ready"},
            status=503,
        )
    except Exception as e:
        return web.json_response(
            {"status": "error", "error": str(e)},
            status=503,
        )


async def start_health_server(host: str = "0.0.0.0", port: int = 8080) -> web.AppRunner:
    """Start the health check HTTP server.

    Args:
        host: Host to bind to (default: 0.0.0.0 for Docker compatibility)
        port: Port to listen on (default: 8080)

    Returns:
        AppRunner instance that can be used to stop the server
    """
    app = web.Application()
    app.add_routes(routes)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, host, port)
    await site.start()

    logger.info(f"Health check server started on http://{host}:{port}")
    return runner


async def stop_health_server(runner: web.AppRunner) -> None:
    """Stop the health check HTTP server."""
    await runner.cleanup()
    logger.info("Health check server stopped")
