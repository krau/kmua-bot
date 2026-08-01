"""Session health monitor tests.

The monitor is the last line of defense against kurigram zombie sessions: a
silently-dead TCP connection leaves the session "started" but unreachable, and
the library's own recovery paths can hang forever (single crypto-executor
thread, unbounded run_in_executor awaits, restart_lock held by a stuck
restart). These tests pin the contracts that keep the watchdog itself alive:

- every probe and every forced restart is hard-bounded, even when the
  underlying library call never returns;
- a failing media/other-DC session is force-restarted after the failure
  threshold (kurigram reuses those sessions forever and never recovers them);
- a main session that stops receiving updates (staleness) is force-restarted,
  and a successful restart resets the staleness clock.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest
from pyrogram.errors import FloodWait, RPCError, UserMigrate

from kmua.session_health import SessionHealthMonitor


class _FakeSession:
    def __init__(self, dc_id: int = 1, invoke_ok: bool = True) -> None:
        self.dc_id = dc_id
        self.is_started = asyncio.Event()
        self.is_started.set()
        self.invoke_ok = invoke_ok
        self.invoke_calls = 0
        self.restart_calls = 0
        self._hang_invoke = asyncio.Event()
        self._hang_restart = asyncio.Event()
        self._never = asyncio.Event()
        self._raise: type[Exception] | None = None

    async def invoke(self, *args, **kwargs):
        self.invoke_calls += 1
        if self._hang_invoke.is_set():
            await self._never.wait()  # never returns
        if self._raise is not None:
            raise self._raise()
        if not self.invoke_ok:
            raise TimeoutError("Request timed out")
        return None

    async def restart(self):
        self.restart_calls += 1
        if self._hang_restart.is_set():
            await self._never.wait()  # never returns
        return None


class _FakeClient:
    def __init__(self, main: _FakeSession) -> None:
        self.session = main
        self.sessions: dict[int, _FakeSession] = {}
        self.media_sessions: dict[int, _FakeSession] = {}
        self.is_connected = True
        self.last_update_time = datetime.now()


def _monitor(
    client: _FakeClient,
    probe_timeout: float = 1.0,
    probe_grace: float = 0.2,
    failure_threshold: int = 3,
    cooldown: float = 0.0,
    stale_threshold: float = 300.0,
    restart_timeout: float = 1.0,
) -> SessionHealthMonitor:
    return SessionHealthMonitor(
        client=client,
        check_interval=60.0,
        probe_timeout=probe_timeout,
        probe_grace=probe_grace,
        failure_threshold=failure_threshold,
        cooldown=cooldown,
        stale_threshold=stale_threshold,
        restart_timeout=restart_timeout,
    )


async def _elapsed(fn) -> tuple[object, float]:
    start = asyncio.get_running_loop().time()
    result = await fn()
    return result, asyncio.get_running_loop().time() - start


@pytest.mark.parametrize(
    "error",
    [UserMigrate, FloodWait],
)
async def test_probe_rpc_error_means_session_alive(error: type[RPCError]) -> None:
    """A rejected RPC (UserMigrate on media sessions, FloodWait) proves the
    send path works - only timeouts/connection errors are liveness failures.
    """
    session = _FakeSession()
    session._raise = error
    monitor = _monitor(_FakeClient(session))

    assert await monitor._probe_session(session) is True
    assert session.invoke_calls == 1


async def test_probe_timeout_means_session_dead() -> None:
    """A timed-out invoke still counts as a liveness failure."""
    session = _FakeSession(invoke_ok=False)
    monitor = _monitor(_FakeClient(session))

    assert await monitor._probe_session(session) is False
    assert session.invoke_calls == 1


async def test_probe_bounded_when_invoke_hangs() -> None:
    """A wedged crypto queue must not hang the monitor's probe forever."""
    session = _FakeSession()
    monitor = _monitor(_FakeClient(session), probe_timeout=0.1, probe_grace=0.2)
    session._hang_invoke.set()

    ok, elapsed = await _elapsed(lambda: monitor._probe_session(session))

    assert ok is False
    assert elapsed < 1.0  # cap is probe_timeout + probe_grace = 0.3s


async def test_restart_bounded_when_restart_hangs() -> None:
    """A stuck library restart must time out and report failure, not block."""
    session = _FakeSession()
    monitor = _monitor(_FakeClient(session), restart_timeout=0.2)
    session._hang_restart.set()

    ok, elapsed = await _elapsed(lambda: monitor._restart_session(session, "test"))

    assert ok is False
    assert elapsed < 1.0


async def test_media_session_restarted_after_failure_threshold() -> None:
    """A silently-dead media session is force-restarted after N failures."""
    main = _FakeSession()
    media = _FakeSession(dc_id=2, invoke_ok=False)
    client = _FakeClient(main)
    client.media_sessions[2] = media
    monitor = _monitor(client, failure_threshold=3)
    loop = asyncio.get_running_loop()

    for _ in range(3):
        await monitor._check_once(loop)

    assert media.restart_calls == 1
    assert media.invoke_calls == 3
    assert main.restart_calls == 0


async def test_media_session_not_restarted_below_threshold() -> None:
    """One probe hiccup is not enough to restart a session."""
    main = _FakeSession()
    media = _FakeSession(dc_id=2, invoke_ok=False)
    client = _FakeClient(main)
    client.media_sessions[2] = media
    monitor = _monitor(client, failure_threshold=3)
    loop = asyncio.get_running_loop()

    await monitor._check_once(loop)

    assert media.restart_calls == 0


async def test_media_session_recovers_and_clears_failure_count() -> None:
    """A session that recovers stops accumulating failures."""
    main = _FakeSession()
    media = _FakeSession(dc_id=2, invoke_ok=False)
    client = _FakeClient(main)
    client.media_sessions[2] = media
    monitor = _monitor(client, failure_threshold=3)
    loop = asyncio.get_running_loop()

    await monitor._check_once(loop)  # failure 1
    await monitor._check_once(loop)  # failure 2
    media.invoke_ok = True
    await monitor._check_once(loop)  # recovery

    assert media.restart_calls == 0
    assert monitor._media_failures == {}


async def test_stale_main_session_triggers_restart_and_resets_clock() -> None:
    """No updates for longer than stale_threshold force-restarts the session."""
    main = _FakeSession()
    client = _FakeClient(main)
    client.last_update_time = datetime.now() - timedelta(seconds=1000)
    monitor = _monitor(client, failure_threshold=3, stale_threshold=300)
    loop = asyncio.get_running_loop()

    for _ in range(3):
        await monitor._check_once(loop)

    assert main.restart_calls == 1
    # A successful restart resets the staleness clock...
    assert datetime.now() - client.last_update_time < timedelta(seconds=1)
    # ...so the next cycle does not immediately re-trigger.
    await monitor._check_once(loop)
    assert main.restart_calls == 1


async def test_healthy_main_session_never_restarts() -> None:
    main = _FakeSession()
    client = _FakeClient(main)
    monitor = _monitor(client)
    loop = asyncio.get_running_loop()

    for _ in range(3):
        await monitor._check_once(loop)

    assert main.restart_calls == 0


async def test_secondary_sessions_collects_media_and_other_dc() -> None:
    main = _FakeSession()
    media = _FakeSession(dc_id=2)
    other = _FakeSession(dc_id=3)
    client = _FakeClient(main)
    client.media_sessions[2] = media
    client.sessions[3] = other
    monitor = _monitor(client)

    sessions = monitor._secondary_sessions()

    assert sessions == [other, media]
    # The main session is never probed twice.
    assert main not in sessions


@pytest.mark.parametrize(
    "pool_attr",
    ["sessions", "media_sessions"],
)
async def test_secondary_session_probed_but_not_restarted_when_healthy(
    pool_attr: str,
) -> None:
    main = _FakeSession()
    secondary = _FakeSession(dc_id=2)
    client = _FakeClient(main)
    getattr(client, pool_attr)[2] = secondary
    monitor = _monitor(client)
    loop = asyncio.get_running_loop()

    await monitor._check_once(loop)

    assert secondary.invoke_calls == 1
    assert secondary.restart_calls == 0
