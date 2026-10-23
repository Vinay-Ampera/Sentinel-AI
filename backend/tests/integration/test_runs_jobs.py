"""Stage 7: runs, batches, worker, cancellation, retries, timeouts and recovery.

Disposable database only (see conftest). The broker is replaced by a recorder and the worker
is driven by calling ``process_batch`` directly with the same arguments a Celery task would
pass, so the tests exercise the real services and PostgreSQL state machine. Real-broker
delivery is covered separately in ``test_celery_broker.py``.
"""

import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from conftest import Env, Session
from fastapi.testclient import TestClient
from test_plans_api import (
    API,
    add_member,
    add_url,
    add_zip_and_analyse,
    decide,
    dev_plan,
    grant_bg,
    new_project,
    request_auth,
    submit,
    user,
)

from sentinel_ai.execution.interface import ExecutionOutcome, ExecutionRequest
from sentinel_ai.execution.stub import NOT_EXECUTED, StubExecutor
from sentinel_ai.services import reconciler, worker_runtime
from support import PEPPER

# Low-risk catalog checks that are runnable for the sample project (openapi_lint is deferred).
CHECKS = ["pytest_unit", "js_unit", "semgrep_static", "bandit_static"]


class WorkerKilled(BaseException):
    """Simulates a worker process dying: not an Exception, so nothing in the worker catches it."""


class Recorder:
    """Stands in for the broker: remembers what the dispatcher published."""

    def __init__(self) -> None:
        self.sent: list[tuple[uuid.UUID, str]] = []
        self.fail = False

    def __call__(self, batch_id: uuid.UUID, task_id: str) -> None:
        if self.fail:
            raise ConnectionError("broker down")
        self.sent.append((batch_id, task_id))


class Probe(StubExecutor):
    """Stub executor with hooks: records calls, can inject outcomes and side effects."""

    def __init__(self) -> None:
        self.calls: list[uuid.UUID] = []
        self.terminated: list[uuid.UUID] = []
        self.terminate_ok = True
        self.on_execute: Callable[[ExecutionRequest, int], None] | None = None
        self.outcome_for: Callable[[ExecutionRequest, int], ExecutionOutcome | None] | None = None

    def execute(
        self, request: ExecutionRequest, should_stop: Callable[[], bool]
    ) -> ExecutionOutcome:
        self.calls.append(request.planned_test_id)
        n = len(self.calls)
        if self.on_execute:
            self.on_execute(request, n)
        if self.outcome_for and (forced := self.outcome_for(request, n)) is not None:
            return forced
        return super().execute(request, should_stop)

    def terminate(self, batch_id: uuid.UUID) -> bool:
        self.terminated.append(batch_id)
        return self.terminate_ok


@pytest.fixture
def make_env(pg: psycopg.Connection, tmp_path: Path) -> Iterator[Callable[..., Env]]:
    clients: list[TestClient] = []

    def build(**settings: Any) -> Env:
        settings = {"job_retry_backoff_seconds": 0.01, **settings}
        e = Env(pg, artifact_storage_dir=tmp_path, **settings)
        e.rec = Recorder()  # type: ignore[attr-defined]
        e.app.state.enqueue = e.rec  # type: ignore[attr-defined]
        client = TestClient(e.app)
        client.__enter__()
        clients.append(client)
        return e

    yield build
    for c in clients:
        c.__exit__(None, None, None)


# ---- helpers ---------------------------------------------------------------------------------


def rec(e: Env) -> Recorder:
    return e.rec  # type: ignore[attr-defined, no-any-return]


def factory(e: Env) -> Any:
    return e.app.state.session_factory


def cfg(e: Env) -> Any:
    return e.app.state.settings


def approved_plan(s: Session, pid: str, src: str, n: int = 5) -> str:
    r = dev_plan(s, pid, [{"check_id": c, "source_id": src} for c in CHECKS[:n]])
    assert r.status_code == 201, r.text
    sub = submit(s, r.json()["id"])
    assert sub.status_code == 200 and sub.json()["status"] == "approved", sub.text
    return str(r.json()["id"])


def start(s: Session, pid: str, plan_id: str, **extra: Any) -> Any:
    headers = {"Idempotency-Key": extra.pop("key")} if "key" in extra else {}
    return s.request(
        "POST",
        f"{API}/projects/{pid}/test-runs",
        json={"plan_id": plan_id, **extra},
        headers=headers,
    )


def setup(
    make_env: Callable[..., Env], n: int = 5, **settings: Any
) -> tuple[Env, dict, Session, str, str, str]:
    e = make_env(**settings)
    dev, s = user(e)
    pid = new_project(s)
    src, _ = add_zip_and_analyse(s, pid)
    plan = approved_plan(s, pid, src, n)
    r = start(s, pid, plan)
    assert r.status_code == 202, r.text
    return e, dev, s, pid, plan, str(r.json()["id"])


def deliver(e: Env, executor: StubExecutor | None = None, *, worker: str = "w1") -> list[str]:
    """Process every published message once, like a worker draining the queue; the finishing
    worker asks the dispatcher for the next batch, as the Celery task does."""
    executor = executor or StubExecutor()
    outcomes = []
    while rec(e).sent:
        batch_id, task_id = rec(e).sent.pop(0)
        outcomes.append(
            worker_runtime.process_batch(factory(e), cfg(e), executor, batch_id, task_id, worker)
        )
        e.app.state.dispatch()
    return outcomes


def sql(e: Env, query: str, *args: Any) -> list[tuple]:
    return e.pg.execute(query, args).fetchall()


def run_status(e: Env, run_id: str) -> str:
    return str(sql(e, "SELECT status FROM public.test_runs WHERE id = %s", run_id)[0][0])


def batch_rows(e: Env, run_id: str) -> list[tuple]:
    return sql(
        e,
        "SELECT ordinal, status, attempt, error_code FROM public.test_batches WHERE run_id = %s ORDER BY ordinal",
        run_id,
    )


def result_statuses(e: Env, run_id: str) -> list[str]:
    return [
        r[0]
        for r in sql(
            e,
            "SELECT status FROM public.test_results WHERE run_id = %s ORDER BY created_at, id",
            run_id,
        )
    ]


def event_types(e: Env, run_id: str) -> list[str]:
    return [
        r[0]
        for r in sql(
            e, "SELECT event_type FROM public.job_events WHERE run_id = %s ORDER BY id", run_id
        )
    ]


def expire_lease(e: Env, run_id: str) -> None:
    e.pg.execute(
        "UPDATE public.test_batches SET lease_expires_at = now() - interval '1 minute' "
        "WHERE run_id = %s AND status IN ('queued', 'dispatched', 'running', 'cancel_requested') "
        "AND lease_expires_at IS NOT NULL",
        (run_id,),
    )


# ---- creating a run --------------------------------------------------------------------------


def test_run_is_split_into_batches_and_dispatched_within_limits(
    make_env: Callable[..., Env],
) -> None:
    e, dev, s, pid, plan, run_id = setup(make_env, 3, job_batch_size=1)
    body = s.request("GET", f"{API}/test-runs/{run_id}").json()
    assert body["status"] == "queued" and body["plan_id"] == plan
    assert body["progress"]["batches_total"] == 3 and body["progress"]["tests_total"] == 3
    assert body["progress"]["results_by_status"] == {} and body["progress"]["tests_finished"] == 0
    batches = s.request("GET", f"{API}/test-runs/{run_id}/batches").json()
    assert [(b["ordinal"], b["status"], b["attempt"]) for b in batches] == [
        (1, "queued", 1),
        (2, "queued", 1),
        (3, "queued", 1),
    ]
    # Per-run limit (2): only two of the three batches were published.
    assert len(rec(e).sent) == 2
    assert [
        r[0]
        for r in sql(e, "SELECT count(*) FROM public.test_batch_items WHERE run_id = %s", run_id)
    ] == [3]
    audit = e.audit("run.create")
    assert audit and audit[0][0] == "success" and audit[0][1] is not None
    assert len(sql(e, "SELECT 1 FROM public.job_events WHERE run_id = %s", run_id)) == 1


def test_global_and_per_run_concurrency_limits(make_env: Callable[..., Env]) -> None:
    e, dev, s, pid, plan, run1 = setup(make_env, 3, job_batch_size=1, job_max_concurrent_batches=3)
    src = sql(e, "SELECT id FROM public.project_sources WHERE project_id = %s", pid)[0][0]
    run2 = start(s, pid, approved_plan(s, pid, str(src), 3)).json()["id"]
    sent = {
        sql(e, "SELECT run_id FROM public.test_batches WHERE id = %s", b)[0][0]
        for b, _ in rec(e).sent
    }
    assert len(rec(e).sent) == 3  # global cap
    counts = sql(
        e,
        "SELECT run_id, count(*) FROM public.test_batches WHERE queue_task_id IS NOT NULL GROUP BY run_id",
    )
    assert {str(r): n for r, n in counts} == {run1: 2, run2: 1}  # oldest run first, two per run
    assert len(sent) == 2
    # Nothing more is sent while all slots are occupied...
    assert e.app.state.dispatch() == 0
    # ...and finishing a batch frees a slot for the next.
    deliver_one = rec(e).sent.pop(0)
    worker_runtime.process_batch(
        factory(e), cfg(e), StubExecutor(), deliver_one[0], deliver_one[1], "w1"
    )
    assert e.app.state.dispatch() == 1


def test_idempotency_key_returns_the_original_run(make_env: Callable[..., Env]) -> None:
    e = make_env(job_batch_size=2)
    dev, s = user(e)
    pid = new_project(s)
    src, _ = add_zip_and_analyse(s, pid)
    plan = approved_plan(s, pid, src, 4)
    first = start(s, pid, plan, key="idem-key-0001")
    again = start(s, pid, plan, key="idem-key-0001")
    assert first.status_code == 202 and again.status_code == 202
    assert first.json()["id"] == again.json()["id"]
    assert sql(e, "SELECT count(*) FROM public.test_runs")[0][0] == 1
    assert sql(e, "SELECT count(*) FROM public.test_batches")[0][0] == 2
    assert len(rec(e).sent) == 2  # the repeat published nothing new
    other = approved_plan(s, pid, src, 3)
    clash = start(s, pid, other, key="idem-key-0001")
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "idempotency_conflict"


def test_run_requires_an_approved_unchanged_plan_and_a_clean_target_gate(
    make_env: Callable[..., Env],
) -> None:
    e = make_env()
    dev, s = user(e)
    admin, a = user(e, "admin")
    pid = new_project(s)
    add_member(s, pid, admin, "manage")
    src, _ = add_zip_and_analyse(s, pid)

    draft = dev_plan(s, pid, [{"check_id": "pytest_unit", "source_id": src}]).json()["id"]
    r = start(s, pid, draft)
    assert r.status_code == 409 and r.json()["error"]["code"] == "approval_required"

    # A high-risk plan stays pending until someone else approves it.
    local = add_url(s, pid, "local")
    pending = dev_plan(s, pid, [{"check_id": "zap_active", "source_id": local}]).json()["id"]
    assert submit(s, pending).json()["status"] == "pending_approval"
    assert start(s, pid, pending).json()["error"]["code"] == "approval_required"

    ok = approved_plan(s, pid, src, 2)
    # An id from another project is a 404, never a hint that it exists.
    other_pid = new_project(s)
    assert start(s, other_pid, ok).status_code == 404
    assert start(s, pid, str(uuid.uuid4())).status_code == 404

    # The frozen content must still match its hash (tampering is simulated by bypassing the triggers).
    e.pg.execute("SET session_replication_role = replica")
    e.pg.execute(
        "UPDATE public.planned_tests SET rationale = 'edited' WHERE plan_id = %s AND ordinal = 1",
        (ok,),
    )
    e.pg.execute("SET session_replication_role = DEFAULT")
    changed = start(s, pid, ok)
    assert changed.status_code == 409 and changed.json()["error"]["code"] == "plan_changed"
    assert sql(e, "SELECT count(*) FROM public.test_runs")[0][0] == 0
    denied = e.audit("run.create")
    assert [d[0] for d in denied].count("denied") >= 3

    # A target that stopped being authorized after approval blocks the run at creation.
    remote = add_url(s, pid, "remote")
    assert request_auth(s, pid, remote).status_code == 201
    aid = a.request("GET", f"{API}/approvals").json()["items"][0]["id"]
    assert decide(a, aid, "approved", "Staging owner agreed to read-only checks").status_code == 200
    smoke = dev_plan(s, pid, [{"check_id": "http_smoke", "source_id": remote}]).json()["id"]
    assert submit(s, smoke).json()["status"] == "approved"
    auth_id = s.request("GET", f"{API}/projects/{pid}/authorizations").json()["items"][0]["id"]
    assert (
        s.request("POST", f"{API}/projects/{pid}/authorizations/{auth_id}/revoke").status_code
        == 200
    )
    blocked = start(s, pid, smoke)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "policy_blocked"
    assert "authorization" in blocked.json()["error"]["details"][0]["issue"]


def test_one_active_run_per_plan_and_archived_projects_are_read_only(
    make_env: Callable[..., Env],
) -> None:
    e, dev, s, pid, plan, run_id = setup(make_env, 2)
    again = start(s, pid, plan)
    assert again.status_code == 409 and again.json()["error"]["code"] == "run_already_active"
    assert s.request("POST", f"{API}/projects/{pid}/archive").status_code in (200, 204)
    assert start(s, pid, plan).status_code == 409


def test_request_cannot_carry_commands_or_flags(make_env: Callable[..., Env]) -> None:
    e = make_env()
    dev, s = user(e)
    pid = new_project(s)
    src, _ = add_zip_and_analyse(s, pid)
    plan = approved_plan(s, pid, src, 1)
    for extra in (
        {"command": "rm -rf /"},
        {"risk_level": "low"},
        {"approved": True},
        {"timeout_seconds": 5},
        {"timeout_seconds": 10**6},
    ):
        r = start(s, pid, plan, **extra)
        assert r.status_code == 422, (extra, r.text)
    short = s.request(
        "POST",
        f"{API}/projects/{pid}/test-runs",
        json={"plan_id": plan},
        headers={"Idempotency-Key": "short"},
    )
    assert short.status_code == 422
    assert start(s, pid, plan, timeout_seconds=120).json()["timeout_seconds"] == 120


# ---- worker: happy path, duplicates ------------------------------------------------------------


def test_worker_runs_batches_in_order_and_never_reports_a_result_it_did_not_produce(
    make_env: Callable[..., Env],
) -> None:
    e, dev, s, pid, plan, run_id = setup(make_env, 4, job_batch_size=2)
    probe = Probe()
    assert deliver(e, probe) == ["completed"] * 2
    assert len(probe.calls) == 4 and len(set(probe.calls)) == 4
    assert run_status(e, run_id) == "completed"
    assert [r[1] for r in batch_rows(e, run_id)] == ["completed"] * 2
    results = s.request("GET", f"{API}/test-runs/{run_id}/results").json()
    assert len(results) == 4
    # The stub executes nothing, so it can only say so: never passed/failed.
    assert {r["status"] for r in results} == {"skipped"} and {r["summary"] for r in results} == {
        NOT_EXECUTED
    }
    body = s.request("GET", f"{API}/test-runs/{run_id}").json()
    assert body["finished_at"] and body["started_at"]
    assert (
        body["progress"]["results_by_status"] == {"skipped": 4}
        and body["progress"]["tests_finished"] == 4
    )
    assert s.request("GET", f"{API}/test-runs/{run_id}/results?status=passed").json() == []
    events = s.request("GET", f"{API}/test-runs/{run_id}/events").json()
    assert [ev["to_status"] for ev in events if ev["batch_id"] is None and ev["to_status"]][
        -1
    ] == "completed"
    last = events[-1]["id"]
    assert s.request("GET", f"{API}/test-runs/{run_id}/events?after={last}").json() == []
    assert len(e.audit("run.start")) == 1 and len(e.audit("run.finish")) == 1
    one = s.request("GET", f"{API}/test-runs/{run_id}/batches").json()[0]
    assert s.request("GET", f"{API}/test-batches/{one['id']}").json()["status"] == "completed"
    # The run id alone grants nothing to a new run of a plan with nothing left to run.
    assert start(s, pid, plan).status_code == 202  # a completed run may be repeated explicitly


def test_duplicate_and_stale_deliveries_do_not_repeat_work(make_env: Callable[..., Env]) -> None:
    e, dev, s, pid, plan, run_id = setup(make_env, 2)
    probe = Probe()
    ((batch_id, task_id),) = rec(e).sent
    assert (
        worker_runtime.process_batch(factory(e), cfg(e), probe, batch_id, task_id, "w1")
        == "completed"
    )
    for _ in range(3):  # at-least-once delivery: the same message arrives again
        assert (
            worker_runtime.process_batch(factory(e), cfg(e), probe, batch_id, task_id, "w2")
            == "noop"
        )
    assert len(probe.calls) == 2 and len(result_statuses(e, run_id)) == 2

    # A message from an earlier dispatch can never claim a batch that was dispatched again.
    e2, _, s2, pid2, plan2, run2 = setup(make_env, 2)
    ((b2, old_task),) = rec(e2).sent
    e2.pg.execute(
        "UPDATE public.test_batches SET lease_expires_at = now() - interval '1 second' WHERE id = %s",
        (b2,),
    )
    rec(e2).sent.clear()
    assert reconciler.reconcile(factory(e2), cfg(e2)).released == 1
    assert e2.app.state.dispatch() == 1
    ((_, new_task),) = rec(e2).sent
    assert new_task != old_task
    probe2 = Probe()
    assert worker_runtime.process_batch(factory(e2), cfg(e2), probe2, b2, old_task, "w1") == "noop"
    assert (
        worker_runtime.process_batch(factory(e2), cfg(e2), probe2, b2, new_task, "w1")
        == "completed"
    )
    assert len(probe2.calls) == 2
    assert worker_runtime.process_batch(factory(e2), cfg(e2), probe2, b2, new_task, "w2") == "noop"


def test_two_workers_racing_for_one_batch_only_one_wins(make_env: Callable[..., Env]) -> None:
    from concurrent.futures import ThreadPoolExecutor

    e, dev, s, pid, plan, run_id = setup(make_env, 3)
    ((batch_id, task_id),) = rec(e).sent
    probe = Probe()
    with ThreadPoolExecutor(4) as pool:
        outcomes = list(
            pool.map(
                lambda w: worker_runtime.process_batch(
                    factory(e), cfg(e), probe, batch_id, task_id, f"w{w}"
                ),
                range(4),
            )
        )
    assert sorted(outcomes) == ["completed", "noop", "noop", "noop"]
    assert len(probe.calls) == 3 and len(result_statuses(e, run_id)) == 3


def test_broker_outage_loses_nothing(make_env: Callable[..., Env]) -> None:
    e = make_env()
    dev, s = user(e)
    pid = new_project(s)
    src, _ = add_zip_and_analyse(s, pid)
    plan = approved_plan(s, pid, src, 2)
    rec(e).fail = True
    r = start(s, pid, plan)
    assert r.status_code == 202  # accepted: PostgreSQL has the run
    run_id = r.json()["id"]
    assert rec(e).sent == []
    assert sql(e, "SELECT queue_task_id FROM public.test_batches WHERE run_id = %s", run_id) == [
        (None,)
    ]
    rec(e).fail = False
    assert e.app.state.dispatch() == 1  # what the periodic dispatcher does
    assert deliver(e) == ["completed"] and run_status(e, run_id) == "completed"


# ---- cancellation ------------------------------------------------------------------------------


def test_queued_run_is_cancelled_at_once_and_late_messages_do_nothing(
    make_env: Callable[..., Env],
) -> None:
    e, dev, s, pid, plan, run_id = setup(make_env, 4, job_batch_size=2)
    r = s.request("POST", f"{API}/test-runs/{run_id}/cancel")
    assert r.status_code == 202 and r.json()["status"] == "cancelled"
    assert [b[1] for b in batch_rows(e, run_id)] == ["cancelled", "cancelled"]
    assert r.json()["cancel_requested_at"] and r.json()["finished_at"]
    probe = Probe()
    assert (
        deliver(e, probe) == ["noop", "noop"] and probe.calls == []
    )  # the queued messages are inert
    again = s.request("POST", f"{API}/test-runs/{run_id}/cancel")
    assert again.status_code == 202 and again.json()["status"] == "cancelled"
    assert len(e.audit("run.cancel")) == 1  # the repeat changed nothing
    assert "cancel_requested" in event_types(e, run_id)
    assert start(s, pid, plan).status_code == 202  # a cancelled plan may be run again


def test_running_cancel_terminates_reports_outcome_and_keeps_finished_batches(
    make_env: Callable[..., Env],
) -> None:
    e, dev, s, pid, plan, run_id = setup(
        make_env, 4, job_batch_size=2, job_max_concurrent_batches_per_run=1
    )
    probe = Probe()
    ((b1, t1),) = rec(e).sent
    assert worker_runtime.process_batch(factory(e), cfg(e), probe, b1, t1, "w1") == "completed"
    e.app.state.dispatch()
    ((b2, t2),) = rec(e).sent[-1:]
    first = sql(e, "SELECT count(*) FROM public.test_results WHERE batch_id = %s", b1)[0][0]

    def cancel_during_second_batch(req: ExecutionRequest, n: int) -> None:
        if n == 3:  # the first test of batch 2
            r = s.request("POST", f"{API}/test-runs/{run_id}/cancel")
            assert r.status_code == 202 and r.json()["status"] == "cancel_requested"

    probe.on_execute = cancel_during_second_batch
    rec(e).sent.clear()
    assert worker_runtime.process_batch(factory(e), cfg(e), probe, b2, t2, "w1") == "cancelled"
    assert probe.terminated == [b2]
    rows = batch_rows(e, run_id)
    assert [r[1] for r in rows] == ["completed", "cancelled"]
    assert run_status(e, run_id) == "cancelled"
    # The completed batch's results survived; the cancelled batch says what did not run.
    assert (
        sql(e, "SELECT count(*) FROM public.test_results WHERE batch_id = %s", b1)[0][0]
        == first
        == 2
    )
    assert set(
        r[0] for r in sql(e, "SELECT status FROM public.test_results WHERE batch_id = %s", b2)
    ) == {"cancelled"}
    detail = sql(
        e,
        "SELECT detail FROM public.job_events WHERE batch_id = %s AND to_status = 'cancelled'",
        b2,
    )[0][0]
    assert detail["termination_confirmed"] is True
    assert e.app.state.dispatch() == 0 and rec(e).sent == []


def test_unconfirmed_termination_is_reported_not_hidden(make_env: Callable[..., Env]) -> None:
    e, dev, s, pid, plan, run_id = setup(make_env, 2)
    probe = Probe()
    probe.terminate_ok = False
    probe.on_execute = lambda req, n: s.request("POST", f"{API}/test-runs/{run_id}/cancel")
    deliver(e, probe)
    assert batch_rows(e, run_id)[0][1:] == ("failed", 1, "cancel_unconfirmed")
    assert run_status(e, run_id) == "failed"


def test_cancel_after_completion_or_by_a_reader_changes_nothing(
    make_env: Callable[..., Env],
) -> None:
    e, dev, s, pid, plan, run_id = setup(make_env, 2)
    reader, r = user(e)
    add_member(s, pid, reader, "read")
    deliver(e)
    assert s.request("POST", f"{API}/test-runs/{run_id}/cancel").json()["status"] == "completed"
    assert r.request("POST", f"{API}/test-runs/{run_id}/cancel").status_code == 403


# ---- retries and timeouts ------------------------------------------------------------------------


def _fail_first_start(req: ExecutionRequest, n: int) -> ExecutionOutcome | None:
    return ExecutionOutcome("failed_to_start", "sandbox image missing") if n == 1 else None


def test_failed_to_start_retries_are_bounded_and_not_reported_as_test_failures(
    make_env: Callable[..., Env],
) -> None:
    e, dev, s, pid, plan, run_id = setup(make_env, 2, job_max_attempts=2)
    probe = Probe()
    probe.outcome_for = _fail_first_start
    assert deliver(e, probe) == ["retry"]
    rows = batch_rows(e, run_id)
    assert rows[0][1] == "queued" and rows[0][2] == 2  # attempt 2 is waiting
    assert "retry_scheduled" in event_types(e, run_id) and run_status(e, run_id) == "running"
    time.sleep(0.2)  # backoff
    assert e.app.state.dispatch() == 1
    assert deliver(e, probe) == ["completed"]
    assert run_status(e, run_id) == "completed"
    statuses = sorted(result_statuses(e, run_id))
    assert statuses == ["failed_to_start", "skipped", "skipped"]  # attempt 1 left on record
    assert "failed" not in statuses and "passed" not in statuses

    e2, _, s2, pid2, plan2, run2 = setup(make_env, 2, job_max_attempts=1)
    probe2 = Probe()
    probe2.outcome_for = _fail_first_start
    deliver(e2, probe2)
    assert batch_rows(e2, run2)[0][1:] == ("failed", 1, "failed_to_start")
    assert run_status(e2, run2) == "failed"
    assert set(result_statuses(e2, run2)) == {"failed_to_start", "skipped"}
    assert s2.request("GET", f"{API}/test-runs/{run2}").json()["error_code"] == "failed_to_start"


def test_batch_timeout_stops_the_batch_and_is_visible(make_env: Callable[..., Env]) -> None:
    e, dev, s, pid, plan, run_id = setup(make_env, 3)
    probe = Probe()
    probe.on_execute = lambda req, n: e.pg.execute(
        "UPDATE public.test_batches SET started_at = now() - interval '2 hours' WHERE run_id = %s",
        (run_id,),
    )
    assert deliver(e, probe) == ["timed_out"]
    assert batch_rows(e, run_id)[0][1] == "timed_out" and run_status(e, run_id) == "timed_out"
    assert probe.terminated and set(result_statuses(e, run_id)) == {"timed_out", "skipped"}
    assert "timeout" in event_types(e, run_id)


def test_run_and_queue_timeouts_are_reconciled(make_env: Callable[..., Env]) -> None:
    # Waited in the queue too long.
    e, dev, s, pid, plan, run_id = setup(make_env, 2)
    e.pg.execute(
        "UPDATE public.test_runs SET created_at = now() - interval '3 hours' WHERE id = %s",
        (run_id,),
    )
    report = reconciler.reconcile(factory(e), cfg(e))
    assert report.runs_timed_out == 1
    body = s.request("GET", f"{API}/test-runs/{run_id}").json()
    assert body["status"] == "timed_out" and body["error_code"] == "queue_timeout"
    assert [b[1] for b in batch_rows(e, run_id)] == ["cancelled"]

    # Started, then exceeded its own limit between batches: finished batches survive.
    e2, _, s2, pid2, plan2, run2 = setup(
        make_env, 4, job_batch_size=2, job_max_concurrent_batches_per_run=1
    )
    ((b1, t1),) = rec(e2).sent
    worker_runtime.process_batch(factory(e2), cfg(e2), StubExecutor(), b1, t1, "w1")
    e2.pg.execute(
        "UPDATE public.test_runs SET started_at = now() - interval '5 hours' WHERE id = %s", (run2,)
    )
    assert reconciler.reconcile(factory(e2), cfg(e2)).runs_timed_out == 1
    assert run_status(e2, run2) == "timed_out"
    assert [b[1] for b in batch_rows(e2, run2)] == ["completed", "cancelled"]
    assert len(result_statuses(e2, run2)) == 2


# ---- revalidation in the worker ------------------------------------------------------------------


def _deactivate(e: Env, who: dict, pid: str) -> None:
    e.pg.execute(
        "UPDATE app_user.users SET is_active = false, deactivated_at = now() WHERE id = %s",
        (who["id"],),
    )


def _remove_access(e: Env, who: dict, pid: str) -> None:
    e.pg.execute("DELETE FROM public.project_memberships WHERE user_id = %s", (who["id"],))


def _archive(e: Env, who: dict, pid: str) -> None:
    e.pg.execute(
        "UPDATE public.projects SET status = 'archived', archived_at = now() WHERE id = %s", (pid,)
    )


@pytest.mark.parametrize("change", [_deactivate, _remove_access, _archive])
def test_worker_refuses_a_batch_when_the_starter_or_project_changed(
    make_env: Callable[..., Env], change: Callable[..., None]
) -> None:
    e = make_env()
    owner, so = user(e)
    runner, sr = user(e)
    pid = new_project(so)
    add_member(so, pid, runner, "run")
    src, _ = add_zip_and_analyse(so, pid)
    plan = approved_plan(so, pid, src, 2)
    assert start(sr, pid, plan).status_code == 202
    change(e, runner, pid)
    probe = Probe()
    assert deliver(e, probe) == ["blocked"]
    assert probe.calls == []  # nothing ran
    assert set(result_statuses(e, str(sql(e, "SELECT id FROM public.test_runs")[0][0]))) == {
        "blocked"
    }
    run_id = str(sql(e, "SELECT id FROM public.test_runs")[0][0])
    assert batch_rows(e, run_id)[0][1:] == ("failed", 1, "revalidation_failed")
    assert run_status(e, run_id) == "failed"


def test_worker_rechecks_the_target_gate_and_policy(make_env: Callable[..., Env]) -> None:
    e = make_env()
    dev, s = user(e)
    admin, a = user(e, "admin")
    pid = new_project(s)
    add_member(s, pid, admin, "manage")
    remote = add_url(s, pid, "remote")
    assert request_auth(s, pid, remote).status_code == 201
    aid = a.request("GET", f"{API}/approvals").json()["items"][0]["id"]
    assert decide(a, aid, "approved", "Staging owner agreed to read-only checks").status_code == 200
    plan = dev_plan(s, pid, [{"check_id": "http_smoke", "source_id": remote}]).json()["id"]
    assert submit(s, plan).json()["status"] == "approved"
    run_id = start(s, pid, plan).json()["id"]  # allowed at creation
    auth_id = s.request("GET", f"{API}/projects/{pid}/authorizations").json()["items"][0]["id"]
    assert (
        s.request("POST", f"{API}/projects/{pid}/authorizations/{auth_id}/revoke").status_code
        == 200
    )
    probe = Probe()
    deliver(e, probe)  # ...revoked before the worker got to it
    assert probe.calls == []
    assert result_statuses(e, run_id) == ["blocked"]
    assert batch_rows(e, run_id)[0][1:] == ("failed", 1, "blocked_by_policy")
    assert run_status(e, run_id) == "failed"
    blocked = sql(e, "SELECT summary FROM public.test_results WHERE run_id = %s", run_id)[0][0]
    assert "authorization" in blocked

    # Policy change: a risk level that is no longer allowed blocks just those tests.
    e2, d2, s2, pid2, plan2, run2 = setup(make_env, 2)
    put = s2.request(
        "PUT", f"{API}/projects/{pid2}/policies/allowed_risk_levels", json={"value": ["medium"]}
    )
    assert put.status_code == 200, put.text
    probe2 = Probe()
    deliver(e2, probe2)
    assert probe2.calls == [] and set(result_statuses(e2, run2)) == {"blocked"}


# ---- recovery ------------------------------------------------------------------------------------


def test_worker_killed_mid_batch_is_recovered_without_repeating_finished_tests(
    make_env: Callable[..., Env],
) -> None:
    e, dev, s, pid, plan, run_id = setup(make_env, 3, job_max_attempts=2)
    ((batch_id, task_id),) = rec(e).sent
    rec(e).sent.clear()  # this worker took the message
    dying = Probe()

    def die_on_second(req: ExecutionRequest, n: int) -> None:
        if n == 2:
            raise WorkerKilled

    dying.on_execute = die_on_second
    with pytest.raises(WorkerKilled):
        worker_runtime.process_batch(factory(e), cfg(e), dying, batch_id, task_id, "w1")
    assert batch_rows(e, run_id)[0][1] == "running" and len(result_statuses(e, run_id)) == 1
    # While the lease is alive the reconciler must leave a possibly-running batch alone.
    assert reconciler.reconcile(factory(e), cfg(e)).total() == 0

    expire_lease(e, run_id)  # the restarted platform sees the lease run out
    report = reconciler.reconcile(factory(e), cfg(e))
    assert report.recovered == 1
    assert batch_rows(e, run_id)[0][1:3] == ("queued", 2)
    assert {"worker_lost", "retry_scheduled"} <= set(event_types(e, run_id))
    assert reconciler.reconcile(factory(e), cfg(e)).total() == 0  # idempotent

    time.sleep(0.2)
    assert e.app.state.dispatch() == 1
    fresh = Probe()
    assert deliver(e, fresh, worker="w2") == ["completed"]
    assert len(fresh.calls) == 2  # the test that already finished is not run again
    assert run_status(e, run_id) == "completed"
    assert (
        sorted(set(result_statuses(e, run_id))) == ["skipped"]
        and len(result_statuses(e, run_id)) == 3
    )


def test_lost_worker_without_retries_fails_visibly_and_a_late_worker_cannot_overwrite(
    make_env: Callable[..., Env],
) -> None:
    e, dev, s, pid, plan, run_id = setup(make_env, 3, job_max_attempts=1)
    probe = Probe()

    def reconciled_meanwhile(req: ExecutionRequest, n: int) -> None:
        if n == 1:
            expire_lease(e, run_id)
            assert reconciler.reconcile(factory(e), cfg(e)).failed == 1

    probe.on_execute = reconciled_meanwhile
    assert deliver(e, probe) == ["lost"]  # the old worker notices and stops writing
    assert batch_rows(e, run_id)[0][1:] == ("failed", 1, "worker_lost")
    assert run_status(e, run_id) == "failed"
    assert s.request("GET", f"{API}/test-runs/{run_id}").json()["error_code"] == "worker_lost"
    assert "worker_lost" in event_types(e, run_id)
    assert len(probe.calls) == 1


def test_worker_lost_while_cancelling_is_reported_as_unconfirmed(
    make_env: Callable[..., Env],
) -> None:
    e, dev, s, pid, plan, run_id = setup(make_env, 2)
    ((batch_id, task_id),) = rec(e).sent
    dying = Probe()
    dying.on_execute = lambda req, n: (_ for _ in ()).throw(WorkerKilled)
    with pytest.raises(WorkerKilled):
        worker_runtime.process_batch(factory(e), cfg(e), dying, batch_id, task_id, "w1")
    assert (
        s.request("POST", f"{API}/test-runs/{run_id}/cancel").json()["status"] == "cancel_requested"
    )
    expire_lease(e, run_id)
    assert reconciler.reconcile(factory(e), cfg(e)).recovered == 1
    assert batch_rows(e, run_id)[0][1:] == ("cancelled", 1, "worker_lost_during_cancel")
    assert run_status(e, run_id) == "cancelled"


def test_cancel_that_is_never_confirmed_is_settled_after_the_grace_period(
    make_env: Callable[..., Env],
) -> None:
    e, dev, s, pid, plan, run_id = setup(make_env, 2)
    ((batch_id, task_id),) = rec(e).sent
    dying = Probe()
    dying.on_execute = lambda req, n: (_ for _ in ()).throw(WorkerKilled)
    with pytest.raises(WorkerKilled):
        worker_runtime.process_batch(factory(e), cfg(e), dying, batch_id, task_id, "w1")
    s.request("POST", f"{API}/test-runs/{run_id}/cancel")
    e.pg.execute(
        "UPDATE public.test_runs SET cancel_requested_at = now() - interval '5 minutes' WHERE id = %s",
        (run_id,),
    )
    assert reconciler.reconcile(factory(e), cfg(e)).cancel_unconfirmed == 1
    assert batch_rows(e, run_id)[0][1:] == ("failed", 1, "cancel_unconfirmed")
    assert run_status(e, run_id) == "failed"


def test_overrunning_batch_whose_worker_is_stuck_is_timed_out(make_env: Callable[..., Env]) -> None:
    e, dev, s, pid, plan, run_id = setup(make_env, 2)
    ((batch_id, task_id),) = rec(e).sent
    stuck = Probe()
    stuck.on_execute = lambda req, n: (_ for _ in ()).throw(WorkerKilled)
    with pytest.raises(WorkerKilled):
        worker_runtime.process_batch(factory(e), cfg(e), stuck, batch_id, task_id, "w1")
    e.pg.execute(
        "UPDATE public.test_batches SET started_at = now() - interval '3 hours' WHERE id = %s",
        (batch_id,),
    )
    assert reconciler.reconcile(factory(e), cfg(e)).timed_out == 1
    assert batch_rows(e, run_id)[0][1:] == ("timed_out", 1, "timeout")
    assert run_status(e, run_id) == "timed_out"


def test_reconciler_finishes_runs_whose_batches_are_all_done(make_env: Callable[..., Env]) -> None:
    e, dev, s, pid, plan, run_id = setup(make_env, 2)
    deliver(e)
    e.pg.execute(
        "SET session_replication_role = replica"
    )  # simulate a crash between the two writes
    e.pg.execute(
        "UPDATE public.test_runs SET status = 'running', finished_at = NULL WHERE id = %s",
        (run_id,),
    )
    e.pg.execute("SET session_replication_role = DEFAULT")
    assert reconciler.reconcile(factory(e), cfg(e)).runs_finalized == 1
    assert run_status(e, run_id) == "completed"


# ---- authorization --------------------------------------------------------------------------------


def test_run_endpoints_are_scoped_to_the_project(make_env: Callable[..., Env]) -> None:
    e, dev, s, pid, plan, run_id = setup(make_env, 2)
    deliver(e)
    batch_id = s.request("GET", f"{API}/test-runs/{run_id}/batches").json()[0]["id"]
    outsider, o = user(e)
    anon = Session(e)
    for method, path in [
        ("GET", f"/test-runs/{run_id}"), ("GET", f"/test-runs/{run_id}/batches"),
        ("GET", f"/test-runs/{run_id}/results"), ("GET", f"/test-runs/{run_id}/events"),
        ("GET", f"/test-batches/{batch_id}"), ("POST", f"/test-runs/{run_id}/cancel"),
        ("GET", f"/projects/{pid}/test-runs"), ("POST", f"/projects/{pid}/test-runs"),
    ]:  # fmt: skip
        kwargs = (
            {"json": {"plan_id": plan}} if method == "POST" and path.endswith("test-runs") else {}
        )
        assert o.request(method, f"{API}{path}", **kwargs).status_code == 404, path
        assert anon.request(method, f"{API}{path}", csrf=False, **kwargs).status_code == 401, path
    assert o.request("GET", f"{API}/test-runs/{uuid.uuid4()}").status_code == 404

    # An Admin or Super Admin has no implicit access either.
    for role in ("admin", "super_admin"):
        _, other = user(e, role)
        assert other.request("GET", f"{API}/test-runs/{run_id}").status_code == 404
        assert other.request("POST", f"{API}/test-runs/{run_id}/cancel").status_code == 404

    reader, r = user(e)
    add_member(s, pid, reader, "read")
    assert r.request("GET", f"{API}/test-runs/{run_id}").status_code == 200
    assert r.request("GET", f"{API}/projects/{pid}/test-runs").status_code == 200
    assert start(r, pid, plan).status_code == 403
    assert r.request("POST", f"{API}/test-runs/{run_id}/cancel").status_code == 403


def test_break_glass_can_read_runs_but_never_start_or_cancel_them(
    make_env: Callable[..., Env],
) -> None:
    e, dev, s, pid, plan, run_id = setup(make_env, 2)
    sup, sa = user(e, "super_admin")
    assert sa.request("GET", f"{API}/test-runs/{run_id}").status_code == 404
    assert grant_bg(sa, pid).status_code == 201
    before = len(e.audit("breakglass.access"))
    assert sa.request("GET", f"{API}/test-runs/{run_id}").status_code == 200
    assert sa.request("GET", f"{API}/test-runs/{run_id}/events").status_code == 200
    assert len(e.audit("breakglass.access")) > before  # every served request is audited
    assert sa.request("POST", f"{API}/test-runs/{run_id}/cancel").status_code == 403
    assert start(sa, pid, plan).status_code == 403
    assert run_status(e, run_id) == "queued"


def test_job_data_does_not_leak_secrets(make_env: Callable[..., Env]) -> None:
    e, dev, s, pid, plan, run_id = setup(make_env, 2)
    deliver(e)
    blob = " ".join(
        str(r)
        for r in sql(e, "SELECT detail FROM public.job_events")
        + sql(e, "SELECT detail FROM public.audit_events")
    )
    for needle in ("s3cretpw", "redis://", PEPPER):
        assert needle not in blob
