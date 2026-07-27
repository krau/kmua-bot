"""In-process rate limiting.

A fixed-capacity sliding window per key, held in memory. kmua runs as a single
process, so there is nothing to coordinate across replicas; if that ever changes
this is the one module to swap for a Redis-backed counter.

The point is to blunt brute-force and accidental request storms, not to meter
usage precisely.
"""

from __future__ import annotations

import time
from collections import deque

from fastapi import status

from kmua.webapp.errors import ApiError, ErrorCode


class SlidingWindowLimiter:
    """Allow at most `limit` events per `window` seconds for each key."""

    def __init__(self, limit: int, window: float) -> None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        if window <= 0:
            raise ValueError("window must be positive")
        self.limit = limit
        self.window = window
        self._hits: dict[str, deque[float]] = {}
        # Bound the key space so a spray of unique keys cannot grow memory
        # without bound.
        self._max_keys = 8192

    def _prune(self, key: str, now: float) -> deque[float]:
        hits = self._hits.get(key)
        if hits is None:
            hits = deque()
            if len(self._hits) >= self._max_keys:
                self._evict_stale(now)
            self._hits[key] = hits
        cutoff = now - self.window
        while hits and hits[0] <= cutoff:
            hits.popleft()
        return hits

    def _evict_stale(self, now: float) -> None:
        cutoff = now - self.window
        stale = [key for key, hits in self._hits.items() if not hits or hits[-1] <= cutoff]
        for key in stale:
            del self._hits[key]
        if len(self._hits) >= self._max_keys:
            # Still full: drop the oldest half rather than refuse service.
            ordered = sorted(self._hits.items(), key=lambda item: item[1][-1])
            for key, _ in ordered[: len(ordered) // 2]:
                del self._hits[key]

    def check(self, key: str, *, now: float | None = None) -> None:
        """Record a hit for `key`, raising `ApiError` (429) when over budget."""
        current = time.monotonic() if now is None else now
        hits = self._prune(key, current)
        if len(hits) >= self.limit:
            retry_after = max(0.0, self.window - (current - hits[0]))
            raise ApiError(
                ErrorCode.RATE_LIMITED,
                "Too many requests, slow down",
                status.HTTP_429_TOO_MANY_REQUESTS,
                details={"retry_after": round(retry_after, 1)},
            )
        hits.append(current)

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._hits.clear()
        else:
            self._hits.pop(key, None)


# Authentication is the one unauthenticated endpoint, so it gets the tightest
# budget and is keyed by client address as well as claimed user.
auth_limiter = SlidingWindowLimiter(limit=20, window=60.0)

# Writes are already authenticated; this only stops runaway clients.
write_limiter = SlidingWindowLimiter(limit=60, window=60.0)
