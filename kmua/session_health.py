"""Telegram session health monitor.

Works around a defect in kurigram/pyrogram's session recovery: when the TCP
connection to Telegram dies silently, the session can enter a "zombie" state
where ``is_started`` stays set but no updates arrive and/or calls fail. The
library schedules ``restart()`` tasks in several places, but they are bare
``create_task`` calls (may be GC'd) and there is no watchdog that detects a
session which *looks* started but can't actually communicate.

This monitor uses two signals:

1. **Invoke probe** (send path): periodically invoke ``updates.GetState`` with
   a short timeout. Failure means the send path is dead.
2. **Update staleness** (recv path): track ``client.last_update_time``. If no
   update has arrived for a long time (far exceeding the server's typical push
   interval), the recv path is likely dead even if invokes still succeed
   (half-open TCP).

When either signal fails repeatedly, the monitor force-restarts the main
session.
"""

import asyncio
from datetime import datetime

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
        stale_threshold: float = 300.0,
    ) -> None:
        """
        Args:
            client: The pyrogram/kurigram client to monitor.
            check_interval: Seconds between health checks.
            probe_timeout: Timeout for each invoke probe.
            failure_threshold: Consecutive probe failures before forcing restart.
            cooldown: Minimum seconds between forced restarts.
            stale_threshold: If no update arrives within this many seconds,
                the recv path is considered dead (half-open TCP).
        """
        self.client = client
        self.check_interval = check_interval
        self.probe_timeout = probe_timeout
        self.failure_threshold = failure_threshold
        self.cooldown = cooldown
        self.stale_threshold = stale_threshold
        self._task: asyncio.Task | None = None
        self._stop = False
        self._consecutive_failures = 0
        self._stale_count = 0
        self._last_restart = 0.0

    async def _probe_invoke(self) -> bool:
        """Probe the send path. Returns True if the invoke succeeds."""
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
                f"session_health: invoke probe failed: "
                f"{e.__class__.__name__} - {e}"
            )
            return False

    def _is_stale(self) -> bool:
        """Check if the recv path is stale (no updates for a long time)."""
        last = getattr(self.client, "last_update_time", None)
        if last is None:
            return False
        elapsed = (datetime.now() - last).total_seconds()
        return elapsed > self.stale_threshold

    async def _force_restart(self, reason: str) -> None:
        logger.warning(
            f"session_health: forcing session restart (reason: {reason})"
        )
        session = self.client.session
        if session is None:
            logger.error("session_health: no session to restart")
            return
        try:
            await session.restart()
            # Reset last_update_time so we don't immediately re-trigger
            # staleness while the session reconnects.
            self.client.last_update_time = datetime.now()
            logger.success("session_health: session restarted successfully")
        except Exception as e:
            logger.error(
                f"session_health: restart failed: "
                f"{e.__class__.__name__} - {e}"
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

            # --- Signal 1: invoke probe (send path) ---
            invoke_ok = await self._probe_invoke()
            if invoke_ok:
                if self._consecutive_failures > 0:
                    logger.info(
                        "session_health: invoke path recovered after "
                        f"{self._consecutive_failures} failure(s)"
                    )
                self._consecutive_failures = 0
            else:
                self._consecutive_failures += 1
                logger.warning(
                    f"session_health: invoke probe failed "
                    f"({self._consecutive_failures}/{self.failure_threshold})"
                )

            # --- Signal 2: update staleness (recv path) ---
            stale = self._is_stale()
            if stale:
                self._stale_count += 1
                last = getattr(self.client, "last_update_time", None)
                elapsed = (
                    (datetime.now() - last).total_seconds() if last else -1
                )
                logger.warning(
                    f"session_health: no updates for {elapsed:.0f}s "
                    f"(stale count: {self._stale_count})"
                )
            else:
                if self._stale_count > 0:
                    logger.info(
                        "session_health: updates resumed after "
                        f"{self._stale_count} stale check(s)"
                    )
                self._stale_count = 0

            # --- Decide whether to force restart ---
            should_restart = (
                self._consecutive_failures >= self.failure_threshold
                or self._stale_count >= self.failure_threshold
            )
            if not should_restart:
                continue

            now = loop.time()
            if now - self._last_restart < self.cooldown:
                logger.debug("session_health: in cooldown, skipping restart")
                continue

            reason_parts = []
            if self._consecutive_failures >= self.failure_threshold:
                reason_parts.append(
                    f"invoke failed {self._consecutive_failures}x"
                )
            if self._stale_count >= self.failure_threshold:
                reason_parts.append(
                    f"updates stale {self._stale_count}x"
                )
            reason = ", ".join(reason_parts)

            self._last_restart = now
            self._consecutive_failures = 0
            self._stale_count = 0
            await self._force_restart(reason)

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
            f"threshold={self.failure_threshold}, "
            f"stale={self.stale_threshold}s, cooldown={self.cooldown}s)"
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
