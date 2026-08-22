"""Event-loop lag monitor.

A small background watchdog that measures asyncio scheduling latency. When the
event loop is blocked (by a synchronous/CPU-bound call, a stuck ``await``, or a
handler that never yields), this monitor will — once the loop runs again — see
that far more time elapsed than expected and emit a warning together with a dump
of the stacks of all currently-running tasks.

This is the fastest way to pinpoint *where* a freeze happens: the next time the
bot hangs, the logs will show which coroutine was on the stack.
"""

import asyncio
import sys
import threading

from kmua.logger import logger
from kmua.webapp.metrics import runtime_metrics

# Frame names that mean "this task is parked waiting for work/events", not
# stuck mid-work. They sort last so real suspects surface within the cap.
_PARKED_FRAMES = frozenset({"get", "wait", "sleep", "recv", "acquire"})


class LoopLagMonitor:
    def __init__(
        self,
        interval: float = 1.0,
        warn_threshold: float = 1.0,
        max_stacks: int = 24,
    ) -> None:
        """
        Args:
            interval: How often (seconds) the watchdog wakes up to measure lag.
            warn_threshold: Extra delay (seconds) beyond ``interval`` that counts
                as a stall worth reporting.
            max_stacks: Maximum number of task stacks to dump per stall.
        """
        self.interval = interval
        self.warn_threshold = warn_threshold
        self.max_stacks = max_stacks
        self._task: asyncio.Task | None = None
        self._stop = False

    async def _loop(self) -> None:
        loop = asyncio.get_running_loop()
        while not self._stop:
            start = loop.time()
            try:
                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                break
            elapsed = loop.time() - start
            lag = elapsed - self.interval
            stalled = lag >= self.warn_threshold
            runtime_metrics.observe_loop_lag(lag, stalled=stalled)
            if stalled:
                logger.warning(
                    f"Event loop stalled for ~{lag:.2f}s "
                    f"(expected {self.interval:.2f}s sleep, took {elapsed:.2f}s). "
                    f"Dumping running task stacks:"
                )
                self._dump_task_stacks()
                self._dump_thread_stacks()

    def _dump_task_stacks(self) -> None:
        try:
            current = asyncio.current_task()
            tasks = [
                t for t in asyncio.all_tasks() if t is not current and not t.done()
            ]
        except Exception as e:
            logger.error(f"loop_monitor: failed to collect tasks: {e}")
            return

        def parked_rank(task: asyncio.Task) -> int:
            try:
                stack = task.get_stack(limit=1)
                if stack and stack[-1].f_code.co_name in _PARKED_FRAMES:
                    return 1
            except Exception:
                pass
            return 0

        tasks.sort(key=parked_rank)

        dumped = 0
        for task in tasks:
            if dumped >= self.max_stacks:
                logger.warning(
                    f"loop_monitor: ... and {len(tasks) - dumped} more tasks"
                )
                break
            try:
                stack = task.get_stack(limit=8)
                if not stack:
                    continue
                frames = []
                for frame in stack:
                    code = frame.f_code
                    frames.append(
                        f"{code.co_filename}:{frame.f_lineno} in {code.co_name}"
                    )
                top = stack[-1]
                if len(stack) == 1 and top.f_lineno == top.f_code.co_firstlineno:
                    # Coroutine created via create_task but never given CPU:
                    # proof the loop had a ready-callback backlog / hard block.
                    frames.append("(scheduled but never ran)")
                stack_text = "\n    ".join(frames)
                logger.warning(
                    f"loop_monitor: task {task.get_name()!r} stack:\n    {stack_text}"
                )
                dumped += 1
            except Exception as e:
                logger.error(f"loop_monitor: failed to dump task stack: {e}")

    def _dump_thread_stacks(self, max_threads: int = 12, limit: int = 6) -> None:
        """Dump non-loop thread stacks.

        Task stacks cannot show a freeze caused outside the loop thread: a
        GIL-hogging C call or an I/O-blocked worker (crypto executor,
        feedparser, log sink) is invisible above. Thread stacks make it
        visible.
        """
        try:
            frames_by_ident = sys._current_frames()
            current_ident = threading.get_ident()
            entries = []
            for th in threading.enumerate():
                ident = th.ident
                if ident is None or ident == current_ident:
                    continue
                frame = frames_by_ident.get(ident)
                if frame is None:
                    continue
                entries.append((th.name, bool(th.daemon), frame))
        except Exception as e:
            logger.error(f"loop_monitor: failed to collect thread stacks: {e}")
            return

        for name, daemon, frame in entries[:max_threads]:
            lines = []
            depth = 0
            while frame is not None and depth < limit:
                lines.append(
                    f"{frame.f_code.co_filename}:{frame.f_lineno}"
                    f" in {frame.f_code.co_name}"
                )
                frame = frame.f_back
                depth += 1
            kind = "daemon" if daemon else "thread"
            logger.warning(
                f"loop_monitor: {kind} {name!r} stack:\n    " + "\n    ".join(lines)
            )
        if len(entries) > max_threads:
            logger.warning(
                f"loop_monitor: ... and {len(entries) - max_threads} more threads"
            )

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop = False
        self._task = asyncio.create_task(self._loop(), name="loop-lag-monitor")
        logger.info(
            f"Event-loop lag monitor started "
            f"(interval={self.interval}s, warn_threshold={self.warn_threshold}s)"
        )

    async def stop(self) -> None:
        self._stop = True
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Event-loop lag monitor stopped")


__all__ = ["LoopLagMonitor"]
