"""In-process sliding-window rate limiter (per key, e.g. client IP).

Limitation: state is per API process, so with N workers the effective limit is N times
higher. The per-account lockout in the database is the authoritative brute-force control;
this only bounds request volume per source address.
"""

import logging
import threading
import time
from collections import deque
from typing import Any

from redis.exceptions import RedisError


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


# ---- shared (Redis) limiter -------------------------------------------------------------------

# One atomic step: refuse when the new total would pass the limit, otherwise add the cost. The
# window index comes from Redis's own clock so API hosts with skewed clocks agree.
_WINDOW_SCRIPT = """
local t = redis.call('TIME')
local window = tonumber(ARGV[3])
local idx = math.floor(tonumber(t[1]) / window)
local key = KEYS[1] .. ':' .. idx
local cur = tonumber(redis.call('GET', key) or '0')
local cost = tonumber(ARGV[1])
if cur + cost > tonumber(ARGV[2]) then return 0 end
local now = redis.call('INCRBY', key, cost)
if now == cost then redis.call('PEXPIRE', key, math.floor(window * 2000)) end
return 1
"""
_PEEK_SCRIPT = """
local t = redis.call('TIME')
local idx = math.floor(tonumber(t[1]) / tonumber(ARGV[2]))
local cur = tonumber(redis.call('GET', KEYS[1] .. ':' .. idx) or '0')
if cur >= tonumber(ARGV[1]) then return 1 end
return 0
"""
logger = logging.getLogger(__name__)
_KEY_MAX = 120


def _safe(part: str) -> str:
    return part[:_KEY_MAX]


class _Degraded:
    """Notes that Redis was unreachable, loudly but at most once a minute and never with the
    connection URL (it can carry a password)."""

    def __init__(self) -> None:
        self.count = 0
        self._last_log = 0.0

    def note(self, what: str, exc: Exception) -> None:
        self.count += 1
        now = time.monotonic()
        if now - self._last_log >= 60:
            self._last_log = now
            logger.warning(
                "%s: Redis unavailable (%s); using the per-process fallback",
                what,
                type(exc).__name__,
            )


class SharedRateLimiter:
    """The same interface as ``RateLimiter`` with the counts kept in Redis, so every API
    process shares one budget (a fixed window; at a window edge up to twice the limit can pass,
    which is documented and acceptable for abuse limiting). If Redis cannot be reached the
    per-process ``fallback`` decides: the limit still applies, only its sharing is lost."""

    def __init__(
        self, client: Any, name: str, max_events: int, window_seconds: float = 60.0,
        fallback: RateLimiter | None = None, degraded: _Degraded | None = None,
    ) -> None:  # fmt: skip
        self._max = max_events
        self._window = window_seconds
        self._name = name
        self._fallback = fallback or RateLimiter(max_events, window_seconds)
        self._degraded = degraded or _Degraded()
        self._allow = client.register_script(_WINDOW_SCRIPT)
        self._peek = client.register_script(_PEEK_SCRIPT)

    @property
    def degraded_count(self) -> int:
        return self._degraded.count

    def _key(self, key: str) -> str:
        return f"sai:rl:{self._name}:{_safe(key)}"

    def allow(self, key: str, cost: int = 1) -> bool:
        try:
            return bool(self._allow(keys=[self._key(key)], args=[cost, self._max, self._window]))
        except (RedisError, OSError) as exc:
            self._degraded.note(f"rate limiter {self._name}", exc)
            return self._fallback.allow(key, cost)

    def blocked(self, key: str) -> bool:
        try:
            return bool(self._peek(keys=[self._key(key)], args=[self._max, self._window]))
        except (RedisError, OSError) as exc:
            self._degraded.note(f"rate limiter {self._name}", exc)
            return self._fallback.blocked(key)


class SharedFlags:
    """Short-lived named markers (for example "this key authenticated recently"), shared through
    Redis with a per-process fallback."""

    def __init__(self, client: Any | None, name: str, ttl_seconds: float) -> None:
        self._client = client
        self._name = name
        self._ttl = ttl_seconds
        self._local: dict[str, float] = {}
        self._degraded = _Degraded()

    def _key(self, flag: str) -> str:
        return f"sai:flag:{self._name}:{_safe(flag)}"

    def set(self, flag: str) -> None:
        if self._client is not None:
            try:
                self._client.set(self._key(flag), b"1", px=int(self._ttl * 1000))
                return
            except (RedisError, OSError) as exc:
                self._degraded.note(f"flag {self._name}", exc)
        if len(self._local) > 10_000:
            self._local.clear()
        self._local[flag] = time.monotonic()

    def has(self, flag: str) -> bool:
        if self._client is not None:
            try:
                return bool(self._client.exists(self._key(flag)))
            except (RedisError, OSError) as exc:
                self._degraded.note(f"flag {self._name}", exc)
        seen = self._local.get(flag)
        return seen is not None and time.monotonic() - seen <= self._ttl
