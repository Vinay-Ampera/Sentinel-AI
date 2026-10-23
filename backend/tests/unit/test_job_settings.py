"""Stage 7 settings, Celery wiring and the stub executor (no database or broker needed)."""

import uuid

import pytest
from pydantic import ValidationError

from sentinel_ai.execution.interface import ExecutionRequest
from sentinel_ai.execution.stub import NOT_EXECUTED, StubExecutor, create_executor
from sentinel_ai.jobs.celery_app import RUN_BATCH, CeleryEnqueuer, make_celery
from support import make_settings


def test_defaults_match_the_approved_design() -> None:
    s = make_settings()
    assert (
        s.job_batch_size,
        s.job_max_concurrent_batches_per_run,
        s.job_max_concurrent_batches,
    ) == (10, 2, 4)
    assert (s.job_lease_seconds, s.job_cancel_grace_seconds, s.job_max_attempts) == (60, 30, 1)
    assert s.job_executor == "stub"


@pytest.mark.parametrize(
    "bad",
    [
        {"job_batch_size": 0},
        {"job_lease_seconds": -1},
        {"job_max_attempts": 4},
        {"job_batch_timeout_seconds": 90000},
        {"job_max_concurrent_batches_per_run": 5, "job_max_concurrent_batches": 4},
        {"job_executor": "docker"},
    ],
)
def test_invalid_job_settings_are_rejected(bad: dict) -> None:
    with pytest.raises(ValidationError):
        make_settings(**bad)


def test_celery_uses_redis_as_a_json_only_broker_without_a_result_backend() -> None:
    s = make_settings(redis_url="redis://:s3cret@cache.internal:6379/0")
    app = make_celery(s)
    conf = app.conf
    assert conf.accept_content == ["json"] and conf.task_serializer == "json"
    assert conf.task_acks_late is True and conf.task_reject_on_worker_lost is True
    assert conf.worker_prefetch_multiplier == 1 and conf.task_ignore_result is True
    assert conf.task_default_queue == "sentinel-jobs"
    assert not conf.result_backend
    assert {"reconcile", "dispatch"} <= set(conf.beat_schedule)
    assert "s3cret" not in repr(s) and "s3cret" not in repr(s.safe_summary())


def test_publisher_fails_fast_when_the_broker_is_unreachable() -> None:
    s = make_settings(redis_url="redis://127.0.0.1:1/0", redis_timeout_seconds=0.2)
    enqueue = CeleryEnqueuer(s)
    with pytest.raises(Exception):  # noqa: B017 - any connection error, never a hang
        enqueue(uuid.uuid4(), "t" * 8)
    assert RUN_BATCH == "sentinel_ai.run_batch"


def test_stub_executor_never_claims_a_result_it_did_not_produce() -> None:
    req = ExecutionRequest(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), "pytest_unit", 1, 60)
    out = StubExecutor().execute(req, lambda: False)
    assert out.status == "skipped" and out.summary == NOT_EXECUTED
    assert StubExecutor().execute(req, lambda: True).status == "cancelled"
    assert StubExecutor().terminate(uuid.uuid4()) is True
    with pytest.raises(ValueError):
        create_executor("docker")
