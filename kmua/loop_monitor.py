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

from kmua.logger import logger
from kmua.webapp.metrics import runtime_metrics


class LoopLagMonitor:
    def __init__(
        self,
        interval: float = 1.0,
        warn_threshold: float = 1.0,
        max_stacks: int = 10,
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

    def _dump_task_stacks(self) -> None:
        try:
            current = asyncio.current_task()
            tasks = [
                t
                for t in asyncio.all_tasks()
                if t is not current and not t.done()
            ]
        except Exception as e:
            logger.error(f"loop_monitor: failed to collect tasks: {e}")
            return

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
                stack_text = "\n    ".join(frames)
                logger.warning(
                    f"loop_monitor: task {task.get_name()!r} stack:\n    {stack_text}"
                )
                dumped += 1
            except Exception as e:
                logger.error(f"loop_monitor: failed to dump task stack: {e}")

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
