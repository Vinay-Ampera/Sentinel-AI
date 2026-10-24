"""Builds the rate limiters the API uses (ADR-0011, Q136).

``RATE_LIMIT_BACKEND=memory`` (the default) keeps every limiter in the API process, as before.
``redis`` counts in Redis so all API processes share one budget; if Redis is unreachable each
limiter falls back to its per-process counter, so a limit never disappears."""

from typing import Any

import redis

from sentinel_ai.core.config import Settings
from sentinel_ai.core.ratelimit import RateLimiter, SharedFlags, SharedRateLimiter


def build_client(settings: Settings) -> Any | None:
    """A lazy Redis client (it connects on first use), or None for the in-process backend."""
    if settings.rate_limit_backend != "redis":
        return None
    timeout = settings.redis_timeout_seconds
    return redis.Redis.from_url(
        settings.redis_url.get_secret_value(),
        socket_connect_timeout=timeout,
        socket_timeout=timeout,
        health_check_interval=0,
    )


def make_limiter(
    client: Any | None, name: str, max_events: int, window_seconds: float = 60.0
) -> RateLimiter | SharedRateLimiter:
    if client is None:
        return RateLimiter(max_events, window_seconds)
    return SharedRateLimiter(client, name, max_events, window_seconds)


def make_flags(client: Any | None, name: str, ttl_seconds: float) -> SharedFlags:
    return SharedFlags(client, name, ttl_seconds)
