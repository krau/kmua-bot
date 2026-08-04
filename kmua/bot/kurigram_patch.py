"""Bound every kurigram crypto-executor await so a saturated queue cannot wedge the session.

kurigram serializes all MTProto crypto (pack of outgoing requests, unpack of
incoming packets, encrypt/decrypt of TCP frames) through one
ThreadPoolExecutor per connection, and every ``run_in_executor(crypto_executor,
...)`` await -- in Session.send, Session.handle_packet, TCP.send and TCP.recv
-- is unbounded. When the queue backs up (concurrent file transfers, a burst
of large update containers), those awaits hang forever: a handler stuck on one
of them freezes the dispatcher (it processes updates one at a time), no
updates are delivered, and invokes timing out with retries re-enqueueing more
pack jobs make the backlog self-sustaining. Raising
Session.CRYPTO_EXECUTOR_WORKERS helps throughput but cannot prevent the
deadlock.

This patch replaces the per-connection crypto ThreadPoolExecutor with a
bounded variant: each submitted job is cancelled (if still queued) after
``session_crypto_timeout`` seconds and the awaiting side receives a
TimeoutError -- which is an OSError subclass, so kurigram treats it as
connection-level: session.send cleans up its pending result, invoke retries,
and the ping worker schedules a session restart. A wedged queue therefore
degrades into bounded timeouts plus kurigram's own recovery machinery instead
of a permanent outage.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module

from kmua.config import app_config
from kmua.logger import logger


class BoundedThreadPoolExecutor(ThreadPoolExecutor):
    """ThreadPoolExecutor whose submitted jobs time out.

    The bound is enforced by the event loop the job is submitted from (the
    same loop kurigram awaits ``run_in_executor`` on): after ``timeout``
    seconds the returned concurrent future resolves with TimeoutError unless
    the job finished first. A job that already started keeps running to
    completion (its CPU work is not wasted); a job still queued is cancelled,
    so the backlog drains.
    """

    def __init__(self, timeout: float, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._timeout = timeout
        self._loop: asyncio.AbstractEventLoop | None = None

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        return self._loop

    def submit(self, fn, /, *args, **kwargs):
        inner = super().submit(fn, *args, **kwargs)
        try:
            loop = self._get_loop()
        except RuntimeError:
            # Used outside a running loop (not how kurigram calls it): fall
            # back to the library's unbounded behavior.
            return inner
        outer = concurrent.futures.Future()
        timer: asyncio.TimerHandle | None = None

        def _on_inner_done(_) -> None:
            if outer.done():
                return
            try:
                result = inner.result()
            except BaseException as exc:  # noqa: BLE001 - surface job errors as-is
                try:
                    outer.set_exception(exc)
                except concurrent.futures.InvalidStateError:
                    pass
            else:
                try:
                    outer.set_result(result)
                except concurrent.futures.InvalidStateError:
                    pass

        def _on_timeout() -> None:
            if outer.done():
                return
            # Set the outer result BEFORE cancelling: cancel() fires the
            # inner done-callback synchronously for a still-queued job, which
            # would otherwise overwrite the TimeoutError with CancelledError.
            try:
                outer.set_exception(
                    TimeoutError(
                        f"crypto executor job timed out after {self._timeout:g}s"
                    )
                )
            except concurrent.futures.InvalidStateError:
                return
            inner.cancel()  # no-op once the job is already running

        def _on_outer_done(_) -> None:
            nonlocal timer
            if outer.cancelled():
                inner.cancel()
            if timer is not None:
                timer.cancel()

        inner.add_done_callback(_on_inner_done)
        timer = loop.call_later(self._timeout, _on_timeout)
        outer.add_done_callback(_on_outer_done)
        return outer


def install() -> None:
    """Replace kurigram's per-connection crypto executor with a bounded one.

    Idempotent. Must run before the first connection is created (the executor
    is built once per TCP connection).
    """
    tcp_module = import_module("pyrogram.connection.transport.tcp.tcp")
    if getattr(tcp_module.ThreadPoolExecutor, "_kmua_bounded", False):
        return
    timeout = app_config.session_crypto_timeout

    def factory(max_workers=None, thread_name_prefix="", *args, **kwargs):
        return BoundedThreadPoolExecutor(
            timeout,
            max_workers=max_workers,
            thread_name_prefix=thread_name_prefix,
            *args,
            **kwargs,
        )

    factory._kmua_bounded = True  # type: ignore[attr-defined]
    # setattr: the module is typed as ModuleType, so a direct attribute
    # assignment is a type error in pyright/pyrefly (same pattern as the
    # Session.CRYPTO_EXECUTOR_WORKERS patch in kmua.bot.client).
    setattr(tcp_module, "ThreadPoolExecutor", factory)
    logger.info(f"kurigram_patch: crypto executor bounded to {timeout:.0f}s per job")


__all__ = ["BoundedThreadPoolExecutor", "install"]
