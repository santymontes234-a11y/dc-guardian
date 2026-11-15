"""Tiny in-memory sliding-window rate limiter (single-process backend)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self, max_events: int, window_s: float):
        self.max_events = max_events
        self.window_s = window_s
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str) -> bool:
        """Register an event for ``key``; return False if the limit is exceeded."""
        now = time.monotonic()
        with self._lock:
            q = self._events[key]
            while q and now - q[0] > self.window_s:
                q.popleft()
            if len(q) >= self.max_events:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
