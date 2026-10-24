"""Shared (Redis) rate limiting (Q136, ADR-0011). Needs ``TEST_REDIS_URL`` (a Redis that may be
written to; every key used here is unique to the test and deleted afterwards)."""

import logging
import os
import time
import uuid
from collections.abc import Iterator

import pytest
import redis
from fastapi.testclient import TestClient

from sentinel_ai.api.observability import IngestLimits
from sentinel_ai.core import limiters
from sentinel_ai.core.ratelimit import RateLimiter, SharedFlags, SharedRateLimiter
from sentinel_ai.main import create_app
from support import ORIGIN, make_settings

URL = os.environ.get("TEST_REDIS_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_REDIS_URL not set")


@pytest.fixture
def client() -> Iterator[redis.Redis]:
    c = redis.Redis.from_url(URL or "", socket_connect_timeout=2, socket_timeout=2)
    yield c
    for key in c.scan_iter("sai:*"):
        if b"t" + b"est-" in key:
            c.delete(key)
    c.close()


def name() -> str:
    return f"test-{uuid.uuid4().hex[:10]}"


def dead_client() -> redis.Redis:
    return redis.Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.2, socket_timeout=0.2)


def test_two_processes_share_one_budget(client: redis.Redis) -> None:
    n = name()
    a, b = SharedRateLimiter(client, n, 5), SharedRateLimiter(client, n, 5)  # two API processes
    assert [a.allow("1.2.3.4") for _ in range(3)] == [True] * 3
    assert [b.allow("1.2.3.4") for _ in range(3)] == [True, True, False]  # 5 in total, not 5 each
    assert a.blocked("1.2.3.4") and b.blocked("1.2.3.4")
    assert not a.blocked("9.9.9.9") and a.allow("9.9.9.9")  # another key has its own budget
    assert a.degraded_count == 0


def test_a_refused_cost_is_not_recorded_and_names_are_separate(client: redis.Redis) -> None:
    n = name()
    lim = SharedRateLimiter(client, n, 5)
    assert lim.allow("k", 3) and not lim.allow("k", 3)  # refused as a whole
    assert lim.allow("k", 2) and not lim.allow("k")
    other = SharedRateLimiter(client, name(), 5)
    assert other.allow("k", 5)  # same key under another limiter name is unaffected


def test_the_window_rolls_over_using_redis_time(client: redis.Redis) -> None:
    lim = SharedRateLimiter(client, name(), 2, window_seconds=1.0)
    assert lim.allow("k", 2) and not lim.allow("k")
    time.sleep(2.2)
    assert lim.allow("k") and not lim.blocked("k")


def test_long_or_hostile_keys_are_bounded(client: redis.Redis) -> None:
    n = name()
    lim = SharedRateLimiter(client, n, 1)
    assert lim.allow("x" * 5000) and not lim.allow("x" * 5000)
    longest = max(len(k) for k in client.scan_iter(f"sai:rl:{n}:*"))
    assert longest < 200


def test_when_redis_is_down_the_per_process_limit_still_applies() -> None:
    # Attach a handler to the module's own logger: other suites (Celery's) reconfigure logging
    # globally, so pytest's caplog is not reliable across the whole run.
    records: list[logging.LogRecord] = []

    class Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    log = logging.getLogger("sentinel_ai.core.ratelimit")
    handler, was_disabled, old_level = Collect(), log.disabled, log.level
    log.disabled, log.propagate = False, True
    log.setLevel(logging.WARNING)
    log.addHandler(handler)
    try:
        lim = SharedRateLimiter(dead_client(), name(), 3, fallback=RateLimiter(3))
        results = [lim.allow("k") for _ in range(5)]
    finally:
        log.removeHandler(handler)
        log.disabled, log.level = was_disabled, old_level
    assert results == [True, True, True, False, False]  # degraded, not unlimited
    assert lim.blocked("k") and lim.degraded_count >= 5
    text = " ".join(r.getMessage() for r in records)
    assert "Redis unavailable" in text
    assert "127.0.0.1:1" not in text and "redis://" not in text  # never the URL


def test_flags_are_shared_expire_and_fall_back(client: redis.Redis) -> None:
    n = name()
    a, b = SharedFlags(client, n, 1.0), SharedFlags(client, n, 1.0)
    assert not b.has("key1")
    a.set("key1")
    assert b.has("key1") and not b.has("key2")
    time.sleep(1.3)
    assert not b.has("key1")  # expired
    down = SharedFlags(dead_client(), n, 5.0)
    down.set("k")
    assert down.has("k") and not down.has("other")  # per-process fallback


def test_the_ingestion_throttle_is_shared_between_processes(client: redis.Redis) -> None:
    s = make_settings(ingest_failed_auth_per_minute=3)
    one, two = IngestLimits(s, client), IngestLimits(s, client)
    # the limiter names are fixed, so use a client-scoped prefix cleanup after the test
    peer = f"test-{uuid.uuid4().hex[:8]}"
    for _ in range(3):
        assert one.failures.allow(peer)
    assert not one.failures.allow(peer)
    assert two.failures.blocked(peer)  # the other process sees the same failures
    one.remember(f"test-{peer}")
    assert two.is_known(f"test-{peer}") and not two.is_known("unseen")
    for key in client.scan_iter(f"sai:*{peer}*"):
        client.delete(key)


def test_the_backend_is_opt_in_and_wired_everywhere() -> None:
    default = create_app(make_settings())
    assert default.state.limiter_client is None
    assert isinstance(default.state.login_limiter, RateLimiter)
    shared = create_app(
        make_settings(rate_limit_backend="redis", redis_url=URL or "redis://localhost")
    )
    assert shared.state.limiter_client is not None
    for lim in (shared.state.login_limiter, shared.state.plan_limiter, shared.state.agent_limiter,
                shared.state.ingest_limits.requests, shared.state.ingest_limits.failures):  # fmt: skip
        assert isinstance(lim, SharedRateLimiter)
    assert limiters.build_client(make_settings()) is None


def test_login_throttling_works_through_redis(client: redis.Redis) -> None:
    settings = make_settings(
        rate_limit_backend="redis", redis_url=URL or "", login_ip_max_attempts_per_minute=2
    )
    app = create_app(settings)
    app.state.login_limiter = SharedRateLimiter(client, name(), 2)  # isolate this test's counters
    with TestClient(
        app, headers={"Origin": ORIGIN}, client=("203.0.113.7", 1), raise_server_exceptions=False
    ) as c:
        body = {"email": "nobody@example.com", "password": "wrong-password-123"}
        codes = [c.post("/api/v1/auth/login", json=body).status_code for _ in range(4)]
    # the first two attempts reach the (absent) database and fail with 500; the limiter, which
    # runs first and counts in Redis, refuses the rest
    assert codes[:2] == [500, 500] and codes[2:] == [429, 429]
