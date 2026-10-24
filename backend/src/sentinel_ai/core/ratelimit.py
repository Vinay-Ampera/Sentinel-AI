"""In-process sliding-window rate limiter (per key, e.g. client IP).

Limitation: state is per API process, so with N workers the effective limit is N times
higher. The per-account lockout in the database is the authoritative brute-force control;
this only bounds request volume per source address.
"""

import threading
import time
from collections import deque


class RateLimiter:
    def __init__(self, max_events: int, window_seconds: float = 60.0) -> None:
        self._max = max_events
        self._window = window_seconds
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def blocked(self, key: str) -> bool:
        """True when the key is already at its limit (nothing is recorded)."""
        now = time.monotonic()
        with self._lock:
            events = self._events.get(key)
            if not events:
                return False
            while events and now - events[0] > self._window:
                events.popleft()
            return len(events) >= self._max

    def allow(self, key: str, cost: int = 1) -> bool:
        """Record ``cost`` attempts; False (and nothing recorded) when they would pass
        ``max_events`` inside the window."""
        now = time.monotonic()
        with self._lock:
            events = self._events.setdefault(key, deque())
            while events and now - events[0] > self._window:
                events.popleft()
            if len(events) + cost > self._max:
                return False
            events.extend([now] * cost)
            if len(self._events) > 10_000:  # bound memory under address churn
                self._events = {
                    k: v for k, v in self._events.items() if v and now - v[-1] <= self._window
                }
            return True
