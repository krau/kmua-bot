"""Runs the FastAPI app on the bot's event loop.

The panel shares kurigram's loop rather than getting a thread or a process of its
own. That is what lets a request call `database.*` and `client.*` directly - no
IPC, no second connection pool, no cache to keep coherent.

The cost is that a slow handler delays message processing, so route code must stay
await-only. The existing `LoopLagMonitor` already reports it when something blocks.
"""

from __future__ import annotations

import asyncio
from typing import Any, cast

import uvicorn

from kmua.common.utils import spawn
from kmua.config import _legacy_health_keys_used, app_config
from kmua.logger import logger
from kmua.webapp import create_app
from kmua.webapp.static import resolve_static_dir, static_bundle_exists


class WebAppServer:
    """Owns the uvicorn server bound to the running loop."""

    def __init__(self) -> None:
        self._server: uvicorn.Server | None = None
        self._task: asyncio.Task | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Start serving. Never raises: the bot must survive a panel failure."""
        if self.running:
            logger.warning("webapp: server already running")
            return

        panel_enabled = _panel_preflight()

        try:
            config = uvicorn.Config(
                create_app(panel_enabled=panel_enabled),
                host=app_config.webapp_host,
                port=app_config.webapp_port,
                # loguru already intercepts stdlib logging; uvicorn's own config
                # would replace those handlers and split the log stream in two.
                log_config=None,
                access_log=False,
                lifespan="on",
                # Behind a reverse proxy, trust X-Forwarded-* so rate limiting and
                # logs see the real client instead of the proxy - but only from the
                # proxy itself. A wildcard here would let any direct caller forge
                # its address and get a fresh rate-limit bucket per request.
                proxy_headers=True,
                forwarded_allow_ips=list(app_config.webapp_trusted_proxies),
            )
            server = uvicorn.Server(config)
            # This process is not uvicorn's: kurigram's idle() owns the signals.
            cast(Any, server).install_signal_handlers = False

            self._server = server
            self._task = spawn(server.serve(), name="webapp-server")
            await self._wait_until_started(server)
        except Exception as e:
            logger.opt(exception=e).error("webapp: failed to start HTTP server")
            self._server = None
            self._task = None
            return

        scope = "panel + health" if panel_enabled else "health only"
        logger.info(
            "webapp: listening on "
            f"http://{app_config.webapp_host}:{app_config.webapp_port} ({scope})"
        )

    async def _wait_until_started(
        self, server: uvicorn.Server, timeout: float = 10.0
    ) -> None:
        """Give the listener a moment to bind so failures surface at startup."""
        deadline = asyncio.get_running_loop().time() + timeout
        while not server.started:
            if self._task is not None and self._task.done():
                # serve() exited early: re-raise whatever it failed with.
                self._task.result()
                return
            if asyncio.get_running_loop().time() > deadline:
                raise TimeoutError("webapp: server did not start in time")
            await asyncio.sleep(0.05)

    async def stop(self, timeout: float = 10.0) -> None:
        """Ask uvicorn to drain and exit, then wait for the task to finish."""
        if self._server is None or self._task is None:
            return

        self._server.should_exit = True
        try:
            await asyncio.wait_for(asyncio.shield(self._task), timeout)
        except TimeoutError:
            logger.warning("webapp: server did not stop in time, cancelling")
            self._task.cancel()
        except Exception as e:
            logger.warning(f"webapp: server stopped with error: {e}")
        finally:
            self._server = None
            self._task = None
            logger.info("webapp: HTTP server stopped")


def _panel_preflight() -> bool:
    """Decide whether the panel can be served, and say why when it cannot.

    A misconfigured panel degrades to health-only rather than taking the bot with
    it: a running bot with no panel beats no bot at all.
    """
    _warn_about_legacy_keys()

    if not app_config.webapp:
        return False

    if not app_config.webapp_url:
        logger.error(
            "webapp: webapp_url is not set, panel disabled. "
            "Telegram only opens Mini Apps over HTTPS, so a public URL is required."
        )
        return False

    if not app_config.webapp_url.startswith("https://"):
        logger.error(
            f"webapp: webapp_url {app_config.webapp_url!r} is not HTTPS, "
            "panel disabled. Telegram refuses to open Mini Apps over plain HTTP."
        )
        return False

    if not static_bundle_exists():
        if app_config.webapp_allow_origins:
            # Dev setup: the bundle is served by `pnpm dev` on another origin,
            # so the API alone is exactly what is wanted here.
            logger.info(
                f"webapp: no bundle at {resolve_static_dir()}, serving API only "
                "for the configured dev origins"
            )
            _warn_about_exposure()
            return True
        logger.error(
            f"webapp: no frontend bundle at {resolve_static_dir()}, panel disabled. "
            "Run `pnpm build` in webapp/ or point webapp_static_dir at the bundle."
        )
        return False

    _warn_about_exposure()
    return True


def _warn_about_legacy_keys() -> None:
    """Nudge deployments still using the pre-panel health check settings.

    They keep working - `webapp_host` / `webapp_port` read them as aliases - but the
    names no longer describe what they configure, since the same server now also
    serves the panel.
    """
    if not _legacy_health_keys_used:
        return
    logger.warning(
        f"webapp: {', '.join(_legacy_health_keys_used)} is deprecated; "
        "rename it to webapp_host / webapp_port. The old name still works for now."
    )


def _warn_about_exposure() -> None:
    """Flag settings that weaken the panel's security posture.

    Only cases that are wrong in every deployment are warned about. A public bind
    address is not one of them: inside a Docker bridge network it is required, and
    `0.0.0.0` is the shipped default. The panel authenticates every request, so an
    exposed port is not an open door - but it does serve plain HTTP, which is why
    the docs put a TLS-terminating proxy in front.
    """
    if "*" in app_config.webapp_trusted_proxies:
        logger.warning(
            "webapp: webapp_trusted_proxies contains '*', so any client can forge "
            "X-Forwarded-For and bypass rate limiting. Set it to the reverse "
            "proxy's address."
        )

    # CORS is warned about in create_app, where the middleware is actually added.


server = WebAppServer()
