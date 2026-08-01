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

When either signal fails repeatedly, the monitor force-restarts the session.
Besides the main session, every cached media/other-DC session is probed the
same way: kurigram reuses those sessions forever and pings them without
checking responses, so a dead media session (failed uploads/downloads, e.g.
avatar refreshes) would otherwise never recover.
"""

import asyncio
from datetime import datetime

from pyrogram import raw
from pyrogram.client import Client
from pyrogram.errors import RPCError

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
        restart_timeout: float = 90.0,
        probe_grace: float = 5.0,
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
            restart_timeout: Hard cap for a forced session.restart() call.
            probe_grace: Extra seconds allowed on top of probe_timeout before a
                probe is declared dead (kurigram's internal send has no
                timeout on its crypto-executor await).
        """
        self.client = client
        self.check_interval = check_interval
        self.probe_timeout = probe_timeout
        self.failure_threshold = failure_threshold
        self.cooldown = cooldown
        self.stale_threshold = stale_threshold
        self.restart_timeout = restart_timeout
        self.probe_grace = probe_grace
        self._task: asyncio.Task | None = None
        self._stop = False
        self._consecutive_failures = 0
        self._stale_count = 0
        self._last_restart = 0.0
        # Per-secondary-session failure / restart bookkeeping, keyed by
        # id(session) so it survives dict churn.
        self._media_failures: dict[int, int] = {}
        self._media_last_restart: dict[int, float] = {}

    async def _probe_session(self, session) -> bool:
        """Probe one session's send path. Returns True if the invoke succeeds."""
        try:
            # kurigram's session.send/handle_packet await run_in_executor (the
            # single crypto thread) WITHOUT a timeout; when that queue is
            # congested the invoke can hang past its own timeout. Hard-cap the
            # whole probe so a wedged session can never hang this monitor.
            await asyncio.wait_for(
                session.invoke(
                    raw.functions.updates.GetState(),
                    retries=1,
                    timeout=self.probe_timeout,
                    # Never sleep on FloodWait inside a probe: raising is the
                    # answer we want (the session is alive).
                    sleep_threshold=0,
                ),
                timeout=self.probe_timeout + self.probe_grace,
            )
            return True
        except RPCError:
            # The session answered: the RPC itself was rejected (e.g.
            # UserMigrate on a media session, whose DC differs from the
            # account's home DC, or a FloodWait), but the send path is alive.
            # Only timeouts/connection errors are liveness failures.
            return True
        except Exception as e:
            logger.debug(
                f"session_health: invoke probe failed: {e.__class__.__name__} - {e}"
            )
            return False

    def _is_stale(self) -> bool:
        """Check if the recv path is stale (no updates for a long time)."""
        last = getattr(self.client, "last_update_time", None)
        if last is None:
            return False
        elapsed = (datetime.now() - last).total_seconds()
        return elapsed > self.stale_threshold

    async def _restart_session(self, session, reason: str) -> bool:
        """Force-restart one session. Returns True on success."""
        logger.warning(f"session_health: forcing session restart (reason: {reason})")
        try:
            # Bound the restart: kurigram's restart() can hang inside stop()
            # (its final ping send awaits the crypto executor without a
            # timeout) while holding restart_lock, which would permanently
            # block every later recovery attempt - including this one. On
            # timeout the cancelled restart unwinds and releases the lock, so
            # the next check cycle can try again.
            await asyncio.wait_for(session.restart(), timeout=self.restart_timeout)
            logger.success("session_health: session restarted successfully")
            return True
        except TimeoutError:
            logger.error(
                "session_health: session restart hung for "
                f">{self.restart_timeout:.0f}s (crypto executor wedged?); "
                "will retry on the next check cycle"
            )
            return False
        except Exception as e:
            logger.error(
                f"session_health: restart failed: {e.__class__.__name__} - {e}"
            )
            return False

    async def _loop(self) -> None:
        loop = asyncio.get_running_loop()
        while not self._stop:
            try:
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            if self._stop or not self.client.is_connected:
                continue

            try:
                await self._check_once(loop)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # A watchdog that dies is worse than a wrong verdict: keep the
                # loop alive no matter what a single check throws.
                logger.error(
                    f"session_health: check failed: {e.__class__.__name__} - {e}"
                )

    async def _check_once(self, loop: asyncio.AbstractEventLoop) -> None:
        """Run one health-check cycle (probe + staleness + possible restarts)."""
        main_session = self.client.session

        # --- Main session: invoke probe (send path) ---
        invoke_ok = main_session is not None and await self._probe_session(main_session)
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

        # --- Main session: update staleness (recv path) ---
        stale = self._is_stale()
        if stale:
            self._stale_count += 1
            last = getattr(self.client, "last_update_time", None)
            elapsed = (datetime.now() - last).total_seconds() if last else -1
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

        # --- Main session: decide whether to force restart ---
        should_restart = (
            self._consecutive_failures >= self.failure_threshold
            or self._stale_count >= self.failure_threshold
        )
        if should_restart and main_session is not None:
            now = loop.time()
            if now - self._last_restart < self.cooldown:
                logger.debug("session_health: in cooldown, skipping restart")
            else:
                reason_parts = []
                if self._consecutive_failures >= self.failure_threshold:
                    reason_parts.append(f"invoke failed {self._consecutive_failures}x")
                if self._stale_count >= self.failure_threshold:
                    reason_parts.append(f"updates stale {self._stale_count}x")
                reason = ", ".join(reason_parts)

                self._last_restart = now
                self._consecutive_failures = 0
                self._stale_count = 0
                if await self._restart_session(main_session, reason):
                    # Reset last_update_time so we don't immediately re-trigger
                    # staleness while the session reconnects.
                    self.client.last_update_time = datetime.now()

        # --- Secondary (media / other-DC) sessions ---
        # kurigram reuses cached sessions forever and pings them with
        # wait_response=False, so a silently-dead media session (the
        # upload.GetFile/avatar-refresh failures) never recovers on its own.
        for session in self._secondary_sessions():
            if not session.is_started.is_set():
                continue
            key = id(session)
            if await self._probe_session(session):
                if key in self._media_failures:
                    logger.info(
                        f"session_health: session DC{session.dc_id} recovered after "
                        f"{self._media_failures.pop(key)} failure(s)"
                    )
                continue
            failures = self._media_failures.get(key, 0) + 1
            self._media_failures[key] = failures
            if failures < self.failure_threshold:
                logger.warning(
                    f"session_health: session DC{session.dc_id} probe failed "
                    f"({failures}/{self.failure_threshold})"
                )
                continue
            now = loop.time()
            if now - self._media_last_restart.get(key, 0.0) < self.cooldown:
                logger.debug(
                    f"session_health: session DC{session.dc_id} in cooldown, "
                    "skipping restart"
                )
                continue
            self._media_last_restart[key] = now
            self._media_failures.pop(key, None)
            await self._restart_session(
                session,
                reason=f"session DC{session.dc_id} invoke failed {failures}x",
            )

    def _secondary_sessions(self) -> list:
        """Cached non-main sessions (media sessions and other-DC sessions)."""
        sessions = []
        seen: set[int] = set()
        main = self.client.session
        for pool in (self.client.sessions, self.client.media_sessions):
            for session in pool.values():
                if session is main or id(session) in seen:
                    continue
                seen.add(id(session))
                sessions.append(session)
        return sessions

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop = False
        self._task = asyncio.create_task(self._loop(), name="session-health-monitor")
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
