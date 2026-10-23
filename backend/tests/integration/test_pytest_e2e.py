"""Stage 9 end to end: plan -> run -> worker -> pytest in the Docker sandbox -> cases, result
detail and evidence download, with authorization checks on every read.

Needs a disposable database (TEST_DATABASE_URL, name ending _test), Docker and the runner
image. Each test uses its own sandbox scope and removes only that scope's containers.
"""

import threading
import time
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import psycopg
import pytest
from conftest import Env, Session
from test_plans_api import (
    API,
    ZIP,
    add_member,
    dev_plan,
    grant_bg,
    new_project,
    submit,
    user,
)
from test_runs_jobs import (  # noqa: F401  (make_env is a fixture)
    batch_rows,
    cfg,
    deliver,
    factory,
    make_env,
    rec,
    result_statuses,
    run_status,
    sql,
    start,
)

from sentinel_ai.execution.docker_runner import DockerRunner
from sentinel_ai.execution.factory import create_executor
from sentinel_ai.services import worker_runtime
from support import make_zip

IMAGE = "sentinel-sandbox-runner:stage8"
_probe = DockerRunner("probe")
pytestmark = pytest.mark.skipif(
    not (_probe.available() and _probe.image_exists(IMAGE)),
    reason="Docker or the sandbox runner image is not available (make sandbox-image)",
)

PROJECT = {
    "calc.py": "def add(a, b):\n    return a + b\n",
    "tests/test_calc.py": (
        "import calc, pytest\n"
        "def test_add(): assert calc.add(1, 2) == 3\n"
        "def test_wrong(): assert calc.add(1, 1) == 3\n"
        "@pytest.mark.skip(reason='later')\n"
        "def test_later(): pass\n"
    ),
}


@pytest.fixture
def denv(make_env: Callable[..., Env]) -> Iterator[Callable[..., tuple[Env, DockerRunner]]]:  # noqa: F811
    made: list[DockerRunner] = []

    def build(**settings: Any) -> tuple[Env, DockerRunner]:
        scope = f"p9-{uuid.uuid4().hex[:10]}"
        opts = {"job_executor": "docker", "sandbox_scope": scope, "sandbox_allow_project_code": True,
                "sandbox_accept_shared_kernel": True, **settings}  # fmt: skip
        runner = DockerRunner(scope)
        made.append(runner)
        return make_env(**opts), runner

    yield build
    for r in made:
        left = r._ids()
        if left:
            r._docker("rm", "-f", "-v", *left)
        assert r._ids() == []


def project(e: Env, files: dict, checks: list[dict] | None = None, s: Session | None = None) -> tuple[Session, str, str]:  # fmt: skip
    """A project with an uploaded ZIP and an approved plan of the given checks."""
    if s is None:
        _, s = user(e)
    pid = new_project(s)
    src = s.request("POST", f"{API}/projects/{pid}/sources/zip", params={"name": "code"}, content=make_zip(files), headers=ZIP)  # fmt: skip
    assert src.status_code == 201, src.text
    sid = src.json()["id"]
    assert s.request("POST", f"{API}/projects/{pid}/analyses", json={"source_id": sid}).status_code == 201  # fmt: skip
    tests = [{"source_id": sid, **c} for c in (checks or [{"check_id": "pytest_unit"}])]
    plan = dev_plan(s, pid, tests).json()
    assert [t["status"] for t in plan["tests"]] == ["planned"] * len(tests), plan["tests"]
    assert submit(s, plan["id"]).json()["status"] == "approved"
    return s, pid, plan["id"]


def worker(e: Env) -> list[str]:
    return deliver(e, create_executor(cfg(e)))


def results(s: Session, run_id: str) -> list[dict]:
    r = s.request("GET", f"{API}/test-runs/{run_id}/results")
    assert r.status_code == 200, r.text
    return list(r.json())


# ---- the whole path ------------------------------------------------------------------------


def test_run_a_pytest_plan_and_inspect_every_result_state_and_evidence(denv: Callable[..., tuple[Env, DockerRunner]]) -> None:  # fmt: skip
    e, runner = denv()
    s, pid, plan = project(e, PROJECT, [{"check_id": "pytest_unit"}, {"check_id": "sandbox_smoke"}, {"check_id": "semgrep_static"}])  # fmt: skip
    run_id = start(s, pid, plan).json()["id"]
    assert worker(e) == ["completed"] and run_status(e, run_id) == "completed"

    by_tool = {r["planned_test_id"]: r for r in results(s, run_id)}
    statuses = sorted(r["status"] for r in by_tool.values())
    assert statuses == [
        "failed",
        "passed",
        "skipped",
    ]  # pytest failed, smoke passed, semgrep has no runner
    failed = next(r for r in by_tool.values() if r["status"] == "failed")
    assert failed["summary"] == "pytest: 1 passed, 1 failed, 1 skipped."

    progress = s.request("GET", f"{API}/test-runs/{run_id}").json()["progress"]
    assert progress["results_by_status"] == {"failed": 1, "passed": 1, "skipped": 1}
    assert progress["cases_by_status"] == {"passed": 1, "failed": 1, "skipped": 1}

    detail = s.request("GET", f"{API}/test-runs/{run_id}/results/{failed['id']}").json()
    assert [(c["name"], c["status"]) for c in detail["cases"]] == [("test_add", "passed"), ("test_wrong", "failed"), ("test_later", "skipped")]  # fmt: skip
    assert "assert 2 == 3" in detail["cases"][1]["message"]
    assert [x["name"] for x in detail["evidence"]] == [
        "junit.xml",
        "manifest.json",
        "stderr.log",
        "stdout.log",
    ]

    # Evidence is downloadable through the project grant, exactly as stored, never rendered.
    for ev in detail["evidence"]:
        r = s.request("GET", f"{API}/artifacts/{ev['id']}/content")
        assert r.status_code == 200, r.text
        assert r.headers["content-disposition"].startswith("attachment; filename=")
        assert (
            r.headers["x-content-type-options"] == "nosniff"
            and "no-store" in r.headers["cache-control"]
        )
        assert "sandbox" in r.headers["content-security-policy"]
        assert len(r.content) == ev["size_bytes"]
    junit = s.request("GET", f"{API}/artifacts/{detail['evidence'][0]['id']}/content")
    assert (
        junit.headers["content-type"].startswith("application/xml")
        and b"test_wrong" in junit.content
    )
    assert len(e.audit("artifact.download")) == 5
    # Cases are stored per result; a result without cases says so honestly.
    smoke = next(r for r in by_tool.values() if r["status"] == "passed")
    assert s.request("GET", f"{API}/test-runs/{run_id}/results/{smoke['id']}").json()["cases"] == []
    assert runner._ids() == []


def test_state_vocabulary_distinguishes_blocked_timed_out_not_run_and_failed_to_start(denv: Callable[..., tuple[Env, DockerRunner]]) -> None:  # fmt: skip
    # blocked: the deployment has not enabled project code.
    e, _ = denv(sandbox_allow_project_code=False, sandbox_accept_shared_kernel=False)
    s, pid, plan = project(e, PROJECT)
    run_id = start(s, pid, plan).json()["id"]
    worker(e)
    assert result_statuses(e, run_id) == ["blocked"] and run_status(e, run_id) == "failed"
    assert (
        "not enabled"
        in sql(e, "SELECT summary FROM public.test_results WHERE run_id = %s", run_id)[0][0]
    )

    # failed_to_start: the sandbox image is missing. Never reported as a test failure.
    e2, _ = denv(sandbox_image="sentinel-no-such-image:none")
    s2, pid2, plan2 = project(e2, PROJECT)
    run2 = start(s2, pid2, plan2).json()["id"]
    worker(e2)
    assert result_statuses(e2, run2) == ["failed_to_start"]
    assert batch_rows(e2, run2)[0][1:] == ("failed", 1, "failed_to_start")
    assert (
        sql(e2, "SELECT count(*) FROM public.test_case_results WHERE run_id = %s", run2)[0][0] == 0
    )

    # timed_out: a test that never ends, with a short plan-level timeout.
    e3, _ = denv()
    loop = {"tests/test_loop.py": "def test_forever():\n    while True:\n        pass\n"}
    s3, pid3, plan3 = project(e3, loop, [{"check_id": "pytest_unit", "parameters": {"timeout_seconds": 10}}])  # fmt: skip
    run3 = start(s3, pid3, plan3).json()["id"]
    started = time.monotonic()
    worker(e3)
    assert result_statuses(e3, run3) == ["timed_out"] and time.monotonic() - started < 60
    assert run_status(e3, run3) == "completed"  # the batch ran; the test timed out

    # not_run: cancelled before the second batch started.
    e4, _ = denv(job_batch_size=1, job_max_concurrent_batches_per_run=1)
    s4, pid4, plan4 = project(
        e4, PROJECT, [{"check_id": "sandbox_smoke"}, {"check_id": "semgrep_static"}]
    )
    run4 = start(s4, pid4, plan4).json()["id"]
    ((b1, t1),) = rec(e4).sent
    worker_runtime.process_batch(factory(e4), cfg(e4), create_executor(cfg(e4)), b1, t1, "w1")
    assert s4.request("POST", f"{API}/test-runs/{run4}/cancel").json()["status"] == "cancelled"
    assert sorted(result_statuses(e4, run4)) == ["not_run", "passed"]


def test_cancelling_stops_a_running_suite_and_records_what_did_not_run(denv: Callable[..., tuple[Env, DockerRunner]]) -> None:  # fmt: skip
    e, runner = denv()
    sleeper = {"tests/test_sleep.py": "import time\ndef test_sleep():\n    time.sleep(60)\n"}
    s, pid, plan = project(e, sleeper, [{"check_id": "pytest_unit"}, {"check_id": "sandbox_smoke"}])
    run_id = start(s, pid, plan).json()["id"]
    ((batch_id, task_id),) = rec(e).sent
    outcome: list[str] = []
    t = threading.Thread(target=lambda: outcome.append(worker_runtime.process_batch(factory(e), cfg(e), create_executor(cfg(e)), batch_id, task_id, "w1")))  # fmt: skip
    t.start()
    deadline = time.time() + 30
    while time.time() < deadline and not runner._ids():
        time.sleep(0.2)
    assert runner._ids(), "the sandbox never started"
    assert (
        s.request("POST", f"{API}/test-runs/{run_id}/cancel").json()["status"] == "cancel_requested"
    )
    t.join(timeout=40)
    assert not t.is_alive() and outcome == ["cancelled"] and runner._ids() == []
    assert sorted(result_statuses(e, run_id)) == ["cancelled", "not_run"]
    assert run_status(e, run_id) == "cancelled"


# ---- authorization -------------------------------------------------------------------------


def test_results_and_evidence_follow_the_project_grant(denv: Callable[..., tuple[Env, DockerRunner]]) -> None:  # fmt: skip
    e, _ = denv()
    owner, so = user(e)
    s, pid, plan = project(e, PROJECT, s=so)
    run_id = start(s, pid, plan).json()["id"]
    worker(e)
    result = results(s, run_id)[0]
    detail = s.request("GET", f"{API}/test-runs/{run_id}/results/{result['id']}").json()
    ev_id = detail["evidence"][0]["id"]
    paths = [f"/test-runs/{run_id}/results/{result['id']}", f"/artifacts/{ev_id}/content"]

    outsider, o = user(e)
    anon = Session(e)
    for p in paths:
        assert s.request("GET", f"{API}{p}").status_code == 200
        assert o.request("GET", f"{API}{p}").status_code == 404  # no hint that it exists
        assert anon.request("GET", f"{API}{p}", csrf=False).status_code == 401
    for role in ("admin", "super_admin"):
        _, other = user(e, role)
        assert [other.request("GET", f"{API}{p}").status_code for p in paths] == [
            404,
            404,
        ]  # no implicit access

    reader, r = user(e)
    add_member(s, pid, reader, "read")
    assert [r.request("GET", f"{API}{p}").status_code for p in paths] == [200, 200]

    # A result id under another run is not found, even for the owner.
    other_plan = project(e, PROJECT, s=so)
    other_run = start(other_plan[0], other_plan[1], other_plan[2]).json()["id"]
    assert (
        s.request("GET", f"{API}/test-runs/{other_run}/results/{result['id']}").status_code == 404
    )

    # Break-glass: read-only, audited, never more.
    sup, sa = user(e, "super_admin")
    assert grant_bg(sa, pid).status_code == 201
    before = len(e.audit("breakglass.access"))
    assert [sa.request("GET", f"{API}{p}").status_code for p in paths] == [200, 200]
    assert len(e.audit("breakglass.access")) >= before + 2
    assert sa.request("POST", f"{API}/test-runs/{run_id}/cancel").status_code == 403


def test_only_run_evidence_is_served_and_tampering_is_detected(denv: Callable[..., tuple[Env, DockerRunner]]) -> None:  # fmt: skip
    e, _ = denv()
    s, pid, plan = project(e, PROJECT)
    run_id = start(s, pid, plan).json()["id"]
    worker(e)
    upload_id = sql(e, "SELECT id FROM public.artifacts WHERE kind = 'upload'")[0][0]
    assert (
        s.request("GET", f"{API}/artifacts/{upload_id}/content").status_code == 404
    )  # uploads are not evidence
    assert s.request("GET", f"{API}/artifacts/{uuid.uuid4()}/content").status_code == 404

    key, art_id = sql(e, "SELECT storage_key, id FROM public.artifacts WHERE run_id = %s AND original_filename = 'stdout.log'", run_id)[0]  # fmt: skip
    path = cfg(e).artifact_root() / key
    path.write_bytes(path.read_bytes() + b"tampered")
    bad = s.request("GET", f"{API}/artifacts/{art_id}/content")
    assert bad.status_code == 409 and bad.json()["error"]["code"] == "artifact_corrupt"
    assert [a[0] for a in e.audit("artifact.download")][-1] == "denied"

    # The database refuses a traversal key outright (defence in depth)...
    with pytest.raises(psycopg.errors.CheckViolation):
        e.pg.execute(
            "UPDATE public.artifacts SET storage_key = 'projects/x/../../etc/passwd' WHERE id = %s",
            (art_id,),
        )
    # ...and a recorded file that has gone missing is a 404, not an error page.
    path.unlink()
    assert s.request("GET", f"{API}/artifacts/{art_id}/content").status_code == 404
