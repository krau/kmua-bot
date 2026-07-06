"""Telegram session health monitor.

Works around a缺陷 in kurigram/pyrogram's session recovery: when the TCP
connection to Telegram dies silently (no OSError, just no responses), the
session enters a "zombie" state — ``is_started`` stays set, but every call
fails after exhausting retries. The library schedules ``restart()`` tasks in
several places, but they are bare ``create_task`` calls with no strong
reference (may be GC'd) and there is no watchdog that detects a session which
*looks* started but can't actually communicate.

This monitor periodically invokes a lightweight raw API call
(``updates.GetState``) with a short timeout. If it fails repeatedly, the
monitor force-restarts the main session, restoring connectivity without
needing a full process restart.
"""

import asyncio

from pyrogram import raw
from pyrogram.client import Client

from kmua.logger import logger


class SessionHealthMonitor:
    def __init__(
        self,
        client: Client,
        check_interval: float = 60.0,
        probe_timeout: float = 15.0,
        failure_threshold: int = 3,
        cooldown: float = 60.0,
    ) -> None:
        """
        Args:
            client: The pyrogram/kurigram client to monitor.
            check_interval: Seconds between health probes.
            probe_timeout: Timeout for each probe invoke.
            failure_threshold: Consecutive failures before forcing a restart.
            cooldown: Minimum seconds between forced restarts (avoids restart storms).
        """
        self.client = client
        self.check_interval = check_interval
        self.probe_timeout = probe_timeout
        self.failure_threshold = failure_threshold
        self.cooldown = cooldown
        self._task: asyncio.Task | None = None
        self._stop = False
        self._consecutive_failures = 0
        self._last_restart = 0.0

    async def _probe(self) -> bool:
        """Return True if the session responds, False on any failure."""
        try:
            session = self.client.session
            if session is None:
                return False
            await session.invoke(
                raw.functions.updates.GetState(),
                retries=1,
                timeout=self.probe_timeout,
            )
            return True
        except Exception as e:
            logger.debug(
                f"session_health: probe failed: {e.__class__.__name__} - {e}"
            )
            return False

    async def _force_restart(self) -> None:
        logger.warning(
            "session_health: session appears dead (zombie state), "
            "forcing restart"
        )
        session = self.client.session
        if session is None:
            logger.error("session_health: no session to restart")
            return
        try:
            await session.restart()
            logger.success("session_health: session restarted successfully")
        except Exception as e:
            logger.error(
                f"session_health: restart failed: {e.__class__.__name__} - {e}"
            )

    async def _loop(self) -> None:
        loop = asyncio.get_running_loop()
        while not self._stop:
            try:
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            if self._stop or not self.client.is_connected:
                continue

            healthy = await self._probe()
            if healthy:
                if self._consecutive_failures > 0:
                    logger.info(
                        "session_health: session recovered after "
                        f"{self._consecutive_failures} failure(s)"
                    )
                self._consecutive_failures = 0
                continue

            self._consecutive_failures += 1
            logger.warning(
                f"session_health: probe failed "
                f"({self._consecutive_failures}/{self.failure_threshold})"
            )

            if self._consecutive_failures >= self.failure_threshold:
                now = loop.time()
                if now - self._last_restart < self.cooldown:
                    logger.debug(
                        "session_health: in cooldown, skipping restart"
                    )
                    continue
                self._last_restart = now
                self._consecutive_failures = 0
                await self._force_restart()

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop = False
        self._task = asyncio.create_task(
            self._loop(), name="session-health-monitor"
        )
        logger.info(
            f"Session health monitor started "
            f"(interval={self.check_interval}s, timeout={self.probe_timeout}s, "
            f"threshold={self.failure_threshold}, cooldown={self.cooldown}s)"
        )

    async def stop(self) -> None:
        self._stop = True
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("Session health monitor stopped")


__all__ = ["SessionHealthMonitor"]
