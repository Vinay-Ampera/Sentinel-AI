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

    def allow(self, key: str) -> bool:
        """Record an attempt; False once ``max_events`` were seen inside the window."""
        now = time.monotonic()
        with self._lock:
            events = self._events.setdefault(key, deque())
            while events and now - events[0] > self._window:
                events.popleft()
            if len(events) >= self._max:
                return False
            events.append(now)
            if len(self._events) > 10_000:  # bound memory under address churn
                self._events = {
                    k: v for k, v in self._events.items() if v and now - v[-1] <= self._window
                }
            return True
