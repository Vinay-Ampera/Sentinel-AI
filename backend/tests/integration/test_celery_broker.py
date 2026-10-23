"""Real-broker check (Stage 7): a Celery worker consumes a batch published through Redis.

Skipped unless both ``TEST_DATABASE_URL`` (a disposable ``*_test`` database) and
``TEST_REDIS_URL`` (a Redis instance that may be written to; it is only used for a uniquely
named queue) are set. Not part of the default run; the tracker records whether it ran.
"""

import os
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path

import pytest
from test_runs_jobs import make_env  # noqa: F401  (fixture)

TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL")
pytestmark = pytest.mark.skipif(
    not (TEST_REDIS_URL and os.environ.get("TEST_DATABASE_URL")),
    reason="TEST_REDIS_URL and TEST_DATABASE_URL not set",
)


def test_batch_published_to_redis_is_processed_by_a_real_celery_worker(
    make_env: Callable[..., object],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from celery.contrib.testing.worker import start_worker
    from test_plans_api import add_zip_and_analyse, new_project, user
    from test_runs_jobs import API, approved_plan, start

    from sentinel_ai.jobs import tasks
    from sentinel_ai.jobs.celery_app import CeleryEnqueuer, make_celery

    queue = f"test-{uuid.uuid4().hex[:8]}"
    e = make_env(redis_url=TEST_REDIS_URL, job_queue_name=queue)  # type: ignore[operator]
    e.app.state.enqueue = CeleryEnqueuer(e.app.state.settings)  # type: ignore[attr-defined]
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"].replace("+psycopg", ""))
    monkeypatch.setenv("REDIS_URL", TEST_REDIS_URL or "")
    monkeypatch.setenv("JOB_QUEUE_NAME", queue)
    monkeypatch.setenv("SESSION_TOKEN_PEPPER", "x" * 40)
    monkeypatch.setenv("SENTINEL_ENV_FILE", os.devnull)
    tasks.runtime.cache_clear()
    from sentinel_ai.core.config import get_settings

    get_settings.cache_clear()

    dev, s = user(e)  # type: ignore[arg-type]
    pid = new_project(s)
    src, _ = add_zip_and_analyse(s, pid)
    app = make_celery(get_settings())
    app.set_default()
    with start_worker(
        app, queues=[queue], perform_ping_check=False, pool="solo", loglevel="WARNING"
    ):
        run_id = start(s, pid, approved_plan(s, pid, src, 2)).json()["id"]
        deadline = time.time() + 30
        status = "queued"
        while time.time() < deadline and status not in ("completed", "failed", "cancelled"):
            time.sleep(0.5)
            status = s.request("GET", f"{API}/test-runs/{run_id}").json()["status"]
    tasks.runtime.cache_clear()  # do not leak this test's settings into other tests
    get_settings.cache_clear()
    assert status == "completed"


def _worker(app_module: str, queue: str, extra_env: dict[str, str]) -> "subprocess.Popen[bytes]":
    env = {
        **os.environ,
        "SENTINEL_ENV_FILE": os.devnull,  # never read a developer's backend/.env
        "DATABASE_URL": os.environ["TEST_DATABASE_URL"].replace("+psycopg", ""),
        "REDIS_URL": TEST_REDIS_URL or "",
        "SESSION_TOKEN_PEPPER": "x" * 40,
        "JOB_QUEUE_NAME": queue,
        "PYTHONPATH": os.pathsep.join(
            [
                str(Path(__file__).resolve().parents[1]),
                str(Path(__file__).resolve().parents[2] / "src"),
            ]
        ),
        **extra_env,
    }
    return subprocess.Popen(  # noqa: S603 - fixed argv, test-only
        [
            sys.executable,
            "-m",
            "celery",
            "-A",
            app_module,
            "worker",
            "-Q",
            queue,
            "--pool",
            "solo",
            "-l",
            "WARNING",
        ],
        env=env,
        cwd=Path(__file__).resolve().parents[1],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_hard_killed_real_worker_is_recovered_and_the_batch_finishes(
    make_env: Callable[..., object],  # noqa: F811
) -> None:
    """kill -9 a live worker mid-batch: its lease expires, the reconciler re-queues the batch
    (bounded), a second worker finishes it, and no test result is duplicated."""
    from test_plans_api import add_zip_and_analyse, new_project, user
    from test_runs_jobs import API, approved_plan, batch_rows, event_types, run_status, sql, start

    from sentinel_ai.jobs.celery_app import CeleryEnqueuer
    from sentinel_ai.services import reconciler

    queue = f"kill-{uuid.uuid4().hex[:8]}"
    knobs = {"JOB_LEASE_SECONDS": "2", "JOB_MAX_ATTEMPTS": "2", "JOB_RETRY_BACKOFF_SECONDS": "0.1"}
    e = make_env(  # type: ignore[operator]
        redis_url=TEST_REDIS_URL, job_queue_name=queue, job_lease_seconds=2,
        job_max_attempts=2, job_retry_backoff_seconds=0.1,
    )  # fmt: skip
    e.app.state.enqueue = CeleryEnqueuer(e.app.state.settings)
    dev, s = user(e)
    pid = new_project(s)
    src, _ = add_zip_and_analyse(s, pid)
    plan = approved_plan(s, pid, src, 2)

    def wait(predicate: Callable[[], bool], seconds: float = 40) -> bool:
        deadline = time.time() + seconds
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(0.3)
        return False

    first = _worker("slow_worker", queue, knobs)
    second = None
    try:
        run_id = start(s, pid, plan).json()["id"]
        assert wait(lambda: batch_rows(e, run_id)[0][1] == "running"), (
            "worker never started the batch"
        )
        first.send_signal(signal.SIGKILL)  # a hard crash: no cleanup, no ack
        first.wait(timeout=10)
        assert batch_rows(e, run_id)[0][1] == "running"  # PostgreSQL still believes it is running

        assert wait(
            lambda: bool(
                sql(
                    e,
                    "SELECT 1 FROM public.test_batches WHERE run_id = %s AND lease_expires_at < clock_timestamp()",
                    run_id,
                )
            ),
            15,
        ), "the lease never expired"
        assert (
            reconciler.reconcile(e.app.state.session_factory, e.app.state.settings).recovered == 1
        )
        assert batch_rows(e, run_id)[0][1:3] == ("queued", 2)

        second = _worker("sentinel_ai.jobs.worker", queue, knobs)
        time.sleep(0.5)  # backoff
        e.app.state.dispatch()  # what the periodic dispatcher does
        assert wait(lambda: run_status(e, run_id) == "completed"), "recovered batch did not finish"
    finally:
        for proc in (first, second):
            if proc is not None and proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=15)

    assert batch_rows(e, run_id)[0][1:3] == ("completed", 2)
    assert {"worker_lost", "retry_scheduled"} <= set(event_types(e, run_id))
    rows = sql(
        e,
        "SELECT planned_test_id, attempt, status FROM public.test_results WHERE run_id = %s",
        run_id,
    )
    assert len(rows) == 2 and len({r[0] for r in rows}) == 2 and {r[2] for r in rows} == {"skipped"}
    assert s.request("GET", f"{API}/test-runs/{run_id}").json()["status"] == "completed"
