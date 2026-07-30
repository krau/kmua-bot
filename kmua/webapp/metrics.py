"""Bounded, process-local metrics for the administrator dashboard."""

from __future__ import annotations

import asyncio
import math
import resource
import threading
import time
from collections import deque
from dataclasses import dataclass

_WINDOW_SECONDS = 15 * 60


_PROFILE_UPDATE_TYPES = frozenset({
    "UpdateNewMessage",
    "UpdateNewChannelMessage",
    "UpdateEditMessage",
    "UpdateEditChannelMessage",
    "UpdateBotCallbackQuery",
    "UpdateInlineBotCallbackQuery",
})

@dataclass(frozen=True)
class RuntimeSnapshot:
    uptime_seconds: int
    max_rss_bytes: int
    threads: int
    tasks: int
    loop_lag_ms: float | None
    loop_lag_p95_ms: float | None
    loop_lag_max_ms: float | None
    loop_stalls: int
    telegram_updates: dict[str, int]
    telegram_update_types: dict[str, int]
    api_requests: dict[str, int]
    api_latency_ms: dict[str, float | None]
    group_activity: list[dict[str, int]]
    feature_calls: dict[str, int]


class RuntimeMetrics:
    """Collect only bounded aggregate data; individual requests are never retained."""

    def __init__(self) -> None:
        self._started_at = time.monotonic()
        self._loop_lags: deque[tuple[float, float]] = deque(maxlen=10_000)
        self._updates: deque[float] = deque(maxlen=10_000)
        self._requests: deque[tuple[float, float, int]] = deque(maxlen=10_000)
        self._update_types: deque[tuple[float, str]] = deque(maxlen=10_000)
        self._activity: deque[tuple[float, int]] = deque(maxlen=10_000)
        self._features: deque[tuple[float, str]] = deque(maxlen=10_000)
        self._loop_stalls = 0

    def _trim(self, now: float) -> None:
        cutoff = now - _WINDOW_SECONDS
        while self._loop_lags and self._loop_lags[0][0] < cutoff:
            self._loop_lags.popleft()
        while self._updates and self._updates[0] < cutoff:
            self._updates.popleft()
        while self._requests and self._requests[0][0] < cutoff:
            self._requests.popleft()
        while self._update_types and self._update_types[0][0] < cutoff:
            self._update_types.popleft()
        while self._activity and self._activity[0][0] < cutoff:
            self._activity.popleft()
        while self._features and self._features[0][0] < cutoff:
            self._features.popleft()

    def observe_loop_lag(self, lag_seconds: float, *, stalled: bool) -> None:
        now = time.monotonic()
        self._loop_lags.append((now, max(0.0, lag_seconds)))
        if stalled:
            self._loop_stalls += 1
        self._trim(now)

    def observe_telegram_update(self, update_type: str) -> None:
        """Record a whitelisted update class without retaining its payload."""
        now = time.monotonic()
        self._updates.append(now)
        if update_type in _PROFILE_UPDATE_TYPES:
            self._update_types.append((now, update_type))
        self._trim(now)

    def observe_group_activity(self, chat_id: int, feature: str | None = None) -> None:
        """Record an aggregate event only; command text and identities are discarded."""
        now = time.monotonic()
        self._activity.append((now, chat_id))
        if feature:
            self._features.append((now, feature))
        self._trim(now)

    def observe_api_request(self, duration_seconds: float, status_code: int) -> None:
        now = time.monotonic()
        self._requests.append((now, max(0.0, duration_seconds), status_code))
        self._trim(now)

    @staticmethod
    def _rate(events: list[float], now: float, seconds: int) -> int:
        return sum(timestamp >= now - seconds for timestamp in events)

    def snapshot(self) -> RuntimeSnapshot:
        now = time.monotonic()
        self._trim(now)
        lags_ms = sorted(lag * 1000 for _, lag in self._loop_lags)
        p95 = lags_ms[math.ceil(len(lags_ms) * 0.95) - 1] if lags_ms else None
        update_times = list(self._updates)
        update_type_counts = {
            update_type: sum(
                timestamp >= now - 300 and recorded_type == update_type
                for timestamp, recorded_type in self._update_types
            )
            for update_type in sorted(_PROFILE_UPDATE_TYPES)
        }
        group_counts: dict[int, int] = {}
        for timestamp, chat_id in self._activity:
            if timestamp >= now - 300:
                group_counts[chat_id] = group_counts.get(chat_id, 0) + 1
        group_activity = [
            {"chat_id": chat_id, "events": events}
            for chat_id, events in sorted(group_counts.items(), key=lambda item: (-item[1], item[0]))[:5]
        ]
        feature_calls: dict[str, int] = {}
        for timestamp, feature in self._features:
            if timestamp >= now - 300:
                feature_calls[feature] = feature_calls.get(feature, 0) + 1
        requests = list(self._requests)
        durations_ms = sorted(duration * 1000 for _, duration, _ in requests)
        latency_p95 = durations_ms[math.ceil(len(durations_ms) * 0.95) - 1] if durations_ms else None
        max_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux reports KiB; macOS reports bytes. kmua is deployed on Linux, keep a
        # conservative normalization for local development.
        max_rss_bytes = max_rss * 1024
        return RuntimeSnapshot(
            uptime_seconds=int(now - self._started_at),
            max_rss_bytes=max_rss_bytes,
            threads=threading.active_count(),
            tasks=len(asyncio.all_tasks()),
            loop_lag_ms=self._loop_lags[-1][1] * 1000 if self._loop_lags else None,
            loop_lag_p95_ms=p95,
            loop_lag_max_ms=lags_ms[-1] if lags_ms else None,
            loop_stalls=self._loop_stalls,
            telegram_updates={str(seconds): self._rate(update_times, now, seconds) for seconds in (60, 300, 900)},
            api_requests={str(seconds): sum(timestamp >= now - seconds for timestamp, _, _ in requests) for seconds in (60, 300, 900)},
            telegram_update_types=update_type_counts,
            api_latency_ms={"p95": latency_p95},
            group_activity=group_activity,
            feature_calls=feature_calls,
        )


runtime_metrics = RuntimeMetrics()

__all__ = ["RuntimeSnapshot", "runtime_metrics"]
