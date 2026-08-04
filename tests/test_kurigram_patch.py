"""Crypto-executor timeout patch contracts (kmua.bot.kurigram_patch).

kurigram awaits pack/unpack/encrypt/decrypt on a per-connection
ThreadPoolExecutor with no timeout; the patch bounds every job so a saturated
queue degrades into TimeoutErrors (an OSError subclass, which kurigram treats
as connection-level) instead of a permanent wedge. These tests exercise the
bounded executor against real threads and a real event loop with short
timeouts.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from kmua.bot.kurigram_patch import BoundedThreadPoolExecutor


async def test_fast_job_completes_with_value():
    pool = BoundedThreadPoolExecutor(timeout=5.0, max_workers=1)
    try:
        fut = pool.submit(lambda: 42)
        assert await asyncio.wrap_future(fut) == 42
    finally:
        pool.shutdown(wait=True)


async def test_job_exception_propagates():
    pool = BoundedThreadPoolExecutor(timeout=5.0, max_workers=1)

    def boom():
        raise ValueError("boom")

    try:
        fut = pool.submit(boom)
        with pytest.raises(ValueError, match="boom"):
            await asyncio.wrap_future(fut)
    finally:
        pool.shutdown(wait=True)


async def test_queued_job_times_out_while_worker_blocked():
    """The awaiting side must get a TimeoutError at the bound, not hang.

    The worker is occupied by a blocked job, so the second job can never
    start; only the timeout can complete its future. The running job is
    allowed to finish (CPU work is not wasted) and the pool keeps working.
    """
    pool = BoundedThreadPoolExecutor(timeout=0.1, max_workers=1)
    gate = threading.Event()
    release = threading.Event()

    def blocker():
        gate.set()
        release.wait(5)

    try:
        first = pool.submit(blocker)
        queued = pool.submit(lambda: 1)
        assert gate.wait(2), "blocker never started"
        start = time.monotonic()
        with pytest.raises(TimeoutError, match="timed out"):
            await asyncio.wrap_future(queued)
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, f"timeout took {elapsed:.2f}s (bound 0.1s)"
        # The running job is not interrupted: release it, retrieve its
        # (already timed-out) future, and the pool must accept new work.
        release.set()
        try:
            await asyncio.wrap_future(first)
        except TimeoutError:
            pass
        fast = pool.submit(lambda: 2)
        assert await asyncio.wrap_future(fast) == 2
    finally:
        release.set()
        pool.shutdown(wait=True)


def test_install_is_idempotent_and_wraps_tcp_executor():
    import importlib

    tcp_module = importlib.import_module("pyrogram.connection.transport.tcp.tcp")

    from kmua.bot import kurigram_patch
    from kmua.config import app_config

    # Importing kmua.bot runs client.py, which already installed the patch;
    # calling install() again must be a no-op.
    kurigram_patch.install()
    kurigram_patch.install()
    factory = tcp_module.ThreadPoolExecutor
    assert getattr(factory, "_kmua_bounded", False)

    loop = asyncio.new_event_loop()
    tcp = tcp_module.TCP(loop=loop)
    try:
        assert isinstance(tcp.crypto_executor, BoundedThreadPoolExecutor)
        assert tcp.crypto_executor._timeout == app_config.session_crypto_timeout
    finally:
        tcp.crypto_executor.shutdown(wait=False)
        loop.close()
