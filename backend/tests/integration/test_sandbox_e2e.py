"""Stage 8 end to end: Stage 7 run -> worker -> Docker sandbox executor -> evidence.

Needs a disposable database (TEST_DATABASE_URL, name ending _test), Docker and the runner
image. Each test uses its own sandbox scope label and removes only containers carrying it.
"""

import hashlib
import json
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from conftest import Env
from test_plans_api import API, add_zip_and_analyse, dev_plan, new_project, submit, user
from test_runs_jobs import (  # noqa: F401  (make_env is a fixture)
    batch_rows,
    cfg,
    deliver,
    event_types,
    factory,
    make_env,
    rec,
    result_statuses,
    run_status,
    sql,
    start,
)

from sentinel_ai.execution import commands
from sentinel_ai.execution.docker_runner import DockerRunner
from sentinel_ai.execution.factory import create_executor
from sentinel_ai.execution.interface import Executor
from sentinel_ai.services import reconciler, worker_runtime

IMAGE = "sentinel-sandbox-runner:stage8"
_probe = DockerRunner("probe")
pytestmark = pytest.mark.skipif(
    not (_probe.available() and _probe.image_exists(IMAGE)),
    reason="Docker or the sandbox runner image is not available (make sandbox-image)",
)

SLEEPER = commands.CheckCommand(
    "sandbox_smoke", ("python", "-I", "-c", "import time; time.sleep(60)")
)


@pytest.fixture
def denv(make_env: Callable[..., Env]) -> Iterator[tuple[Env, DockerRunner]]:  # noqa: F811
    scope = f"e2e-{uuid.uuid4().hex[:10]}"
    e = make_env(job_executor="docker", sandbox_scope=scope)
    runner = DockerRunner(scope)
    yield e, runner
    left = runner._ids()  # only this test's scope
    if left:
        runner._docker("rm", "-f", "-v", *left)
    assert runner._ids() == []


def smoke_plan(e: Env, extra: list[str] | None = None) -> tuple[Any, str, str, str]:
    dev, s = user(e)
    pid = new_project(s)
    src, _ = add_zip_and_analyse(s, pid)
    tests = [{"check_id": c, "source_id": src} for c in ["sandbox_smoke", *(extra or [])]]
    plan = dev_plan(s, pid, tests).json()
    assert [t["status"] for t in plan["tests"]] == ["planned"] * len(tests), plan["tests"]
    assert submit(s, plan["id"]).json()["status"] == "approved"
    return s, pid, plan["id"], src


def executor_for(e: Env) -> Executor:
    return create_executor(cfg(e))


def test_default_executor_is_still_the_stub(make_env: Callable[..., Env]) -> None:  # noqa: F811
    from sentinel_ai.execution.stub import StubExecutor

    assert isinstance(create_executor(cfg(make_env())), StubExecutor)


def test_smoke_check_runs_in_a_real_sandbox_and_stores_evidence(denv: tuple[Env, DockerRunner]) -> None:  # fmt: skip
    e, runner = denv
    s, pid, plan, src = smoke_plan(e)
    run_id = start(s, pid, plan).json()["id"]
    assert deliver(e, executor_for(e)) == ["completed"]
    assert run_status(e, run_id) == "completed" and result_statuses(e, run_id) == ["passed"]
    (summary, exit_code), = sql(e, "SELECT summary, exit_code FROM public.test_results WHERE run_id = %s", run_id)  # fmt: skip
    assert exit_code == 0 and "exit code 0" in summary

    rows = sql(e, "SELECT original_filename, kind, storage_key, sha256, size_bytes, redaction_status, project_id, result_id FROM public.artifacts WHERE run_id = %s ORDER BY original_filename", run_id)  # fmt: skip
    assert [(r[0], r[1]) for r in rows] == [("manifest.json", "report"), ("stderr.log", "log"), ("stdout.log", "log")]  # fmt: skip
    root = cfg(e).artifact_root()
    blobs = {}
    for name, _kind, key, digest, size, redaction, project, result in rows:
        assert key.startswith(f"projects/{project}/runs/{run_id}/results/{result}/") and ".." not in key  # fmt: skip
        data = (root / key).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest.strip() and len(data) == size
        assert redaction == "redacted"
        blobs[name] = data
    census = json.loads(blobs["stdout.log"])
    assert census["files"] == 11 and census["project_code_executed"] is False and census["uid"] == 65534  # fmt: skip
    manifest = json.loads(blobs["manifest.json"])
    assert manifest["network"] == "none" and manifest["container_removed"] is True
    assert manifest["container"]["ReadonlyRootfs"] is True and manifest["container"]["Privileged"] is False  # fmt: skip
    assert manifest["exit_code"] == 0 and manifest["limits"]["memory_mb"] == 512
    assert runner._ids() == []  # the container is gone


def test_checks_without_a_runner_are_skipped_and_never_start_a_container(denv: tuple[Env, DockerRunner]) -> None:  # fmt: skip
    e, runner = denv
    s, pid, plan, _ = smoke_plan(e, ["semgrep_static"])
    run_id = start(s, pid, plan).json()["id"]
    deliver(e, executor_for(e))
    assert sorted(result_statuses(e, run_id)) == ["passed", "skipped"]
    skipped = sql(e, "SELECT summary FROM public.test_results WHERE run_id = %s AND status = 'skipped'", run_id)[0][0]  # fmt: skip
    assert "no sandbox runner" in skipped
    assert sql(e, "SELECT count(*) FROM public.artifacts WHERE run_id = %s", run_id)[0][0] == 3  # only the smoke check has evidence  # fmt: skip


def test_tampered_archive_is_blocked_before_any_container(denv: tuple[Env, DockerRunner]) -> None:  # fmt: skip
    e, runner = denv
    s, pid, plan, _ = smoke_plan(e)
    key = sql(e, "SELECT storage_key FROM public.artifacts WHERE kind = 'upload'")[0][0]
    path = cfg(e).artifact_root() / key
    path.write_bytes(path.read_bytes() + b"tampered")  # no longer matches the recorded hash
    run_id = start(s, pid, plan).json()["id"]
    deliver(e, executor_for(e))
    assert result_statuses(e, run_id) == ["blocked"]
    summary = sql(e, "SELECT summary FROM public.test_results WHERE run_id = %s", run_id)[0][0]
    assert "hash" in summary and runner._ids() == []
    assert batch_rows(e, run_id)[0][1:] == ("failed", 1, "blocked_by_policy")
    assert run_status(e, run_id) == "failed"


def test_workspace_is_only_the_runs_own_project_source(denv: tuple[Env, DockerRunner]) -> None:  # fmt: skip
    e, _ = denv
    s_a, pid_a, plan_a, src_a = smoke_plan(e)
    run_a = start(s_a, pid_a, plan_a).json()["id"]
    s_b, pid_b, plan_b, _ = smoke_plan(e)
    run_b = start(s_b, pid_b, plan_b).json()["id"]
    from sentinel_ai.repositories import plans, runs

    with factory(e)() as db:
        ra, rb = runs.get_run(db, uuid.UUID(run_a)), runs.get_run(db, uuid.UUID(run_b))
        assert ra and rb
        test_a = plans.list_tests(db, ra.plan_id)[0]
        assert worker_runtime._workspace(db, ra, test_a) is not None
        assert worker_runtime._workspace(db, rb, test_a) is None  # another project's source


def _wait_for_container(runner: DockerRunner, seconds: float = 30) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if runner._ids():
            return True
        time.sleep(0.2)
    return False


def test_cancelling_a_run_terminates_its_running_container(denv: tuple[Env, DockerRunner], monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    e, runner = denv
    monkeypatch.setitem(commands.COMMANDS, "sandbox_smoke", SLEEPER)
    s, pid, plan, _ = smoke_plan(e)
    run_id = start(s, pid, plan).json()["id"]
    ((batch_id, task_id),) = rec(e).sent
    outcome: list[str] = []
    worker = threading.Thread(
        target=lambda: outcome.append(
            worker_runtime.process_batch(
                factory(e), cfg(e), executor_for(e), batch_id, task_id, "w1"
            )
        )  # fmt: skip
    )
    worker.start()
    assert _wait_for_container(runner), "the sandbox never started"
    begin = time.time()
    assert s.request("POST", f"{API}/test-runs/{run_id}/cancel").json()["status"] == "cancel_requested"  # fmt: skip
    worker.join(timeout=30)
    assert not worker.is_alive() and time.time() - begin < 20
    assert outcome == ["cancelled"] and runner._ids() == []
    assert run_status(e, run_id) == "cancelled" and batch_rows(e, run_id)[0][1] == "cancelled"
    assert result_statuses(e, run_id) == ["cancelled"]
    detail = sql(e, "SELECT detail FROM public.job_events WHERE run_id = %s AND to_status = 'cancelled' AND batch_id IS NOT NULL", run_id)[0][0]  # fmt: skip
    assert detail["termination_confirmed"] is True


def test_reconciler_removes_the_sandbox_a_lost_worker_left_behind(denv: tuple[Env, DockerRunner], monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    e, runner = denv
    monkeypatch.setitem(commands.COMMANDS, "sandbox_smoke", SLEEPER)
    s, pid, plan, _ = smoke_plan(e)
    run_id = start(s, pid, plan).json()["id"]
    ((batch_id, task_id),) = rec(e).sent
    executor = executor_for(e)
    outcome: list[str] = []
    worker = threading.Thread(
        target=lambda: outcome.append(
            worker_runtime.process_batch(factory(e), cfg(e), executor, batch_id, task_id, "w1")
        )  # fmt: skip
    )
    worker.start()
    assert _wait_for_container(runner)
    # The worker "dies": its lease stops being renewed and runs out.
    e.pg.execute("UPDATE public.test_batches SET lease_expires_at = now() - interval '1 minute' WHERE run_id = %s", (run_id,))  # fmt: skip
    report = reconciler.reconcile(factory(e), cfg(e), cleanup=executor.terminate, sweep=executor.sweep)  # type: ignore[attr-defined]  # fmt: skip
    assert report.failed == 1
    detail = sql(e, "SELECT detail FROM public.job_events WHERE run_id = %s AND event_type = 'worker_lost'", run_id)[0][0]  # fmt: skip
    assert detail["sandbox_cleanup_confirmed"] is True
    worker.join(timeout=30)
    assert not worker.is_alive() and outcome == ["lost"] and runner._ids() == []
    assert batch_rows(e, run_id)[0][1:] == ("failed", 1, "worker_lost")
    # The late worker did not record the killed container as a failed test.
    assert result_statuses(e, run_id) == ["not_run"] and run_status(e, run_id) == "failed"


def test_janitor_removes_a_leaked_container_during_reconcile(denv: tuple[Env, DockerRunner]) -> None:  # fmt: skip
    from sentinel_ai.execution.sandbox_spec import SandboxLimits, SandboxSpec, create_argv

    e, runner = denv
    lim = SandboxLimits(1.0, 128, 64, 32, 8, 20, 16, 8, 500, 2_000_000, 65536)
    leaked = SandboxSpec(IMAGE, runner.scope, uuid.uuid4(), uuid.uuid4(), ("python", "-I", "-c", "print(1)"), lim, False)  # fmt: skip
    assert runner._docker(*create_argv(runner.docker_bin, "sentinel-sbx-leak" + uuid.uuid4().hex[:8], leaked)[1:])[0] == 0  # fmt: skip
    executor = executor_for(e)
    assert reconciler.reconcile(factory(e), cfg(e), sweep=executor.sweep).containers_swept == 0  # type: ignore[attr-defined]  # fmt: skip
    # Make it "old" by sweeping with a zero age through the runner the executor uses.
    time.sleep(1.1)
    assert runner.sweep(1) == 1 and runner._ids() == []


def test_event_log_records_the_sandboxed_run(denv: tuple[Env, DockerRunner]) -> None:
    e, _ = denv
    s, pid, plan, _ = smoke_plan(e)
    run_id = start(s, pid, plan).json()["id"]
    deliver(e, executor_for(e))
    assert {"transition"} <= set(event_types(e, run_id))
    assert [a[0] for a in e.audit("run.start")] == ["success"] and [a[0] for a in e.audit("run.finish")] == ["success"]  # fmt: skip
