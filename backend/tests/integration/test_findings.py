"""Stage 10 integration: scanner findings end to end.

DB-level tests need a disposable database (TEST_DATABASE_URL, name ending _test) and use the
stub executor only to obtain real run/result ids. The Docker tests also need the sandbox
image (make sandbox-image) and run the real Bandit in a real, locked-down container.
"""

import uuid
from collections.abc import Callable
from typing import Any

import psycopg
import pytest
from conftest import Env, Session
from test_plans_api import API, add_member, grant_bg, user
from test_pytest_e2e import denv, project, results, worker  # noqa: F401 (denv is a fixture)
from test_runs_jobs import cfg, deliver, factory, make_env, sql, start  # noqa: F401

from sentinel_ai.execution.docker_runner import DockerRunner
from sentinel_ai.execution.interface import FindingResult, ScanOutcome
from sentinel_ai.repositories import runs as runs_repo
from sentinel_ai.services import findings as svc

IMAGE = "sentinel-sandbox-runner:stage8"
_probe = DockerRunner("probe")
docker_required = pytest.mark.skipif(
    not (_probe.available() and _probe.image_exists(IMAGE)),
    reason="Docker or the sandbox runner image is not available (make sandbox-image)",
)
BANDIT = [{"check_id": "bandit_static"}]
LIMITS = "Static pattern match; nothing was executed."


def fr(rule: str = "B602", path: str = "a.py", line: int = 3, sev: str = "high", conf: str = "high", n: int = 0) -> FindingResult:  # fmt: skip
    return FindingResult("bandit", rule, f"{rule}: finding", sev, conf, path, line, "message", f"bandit:{rule}:{path}:{n}", 78)  # fmt: skip


def scan(*found: FindingResult, complete: bool = True) -> ScanOutcome:
    return ScanOutcome("bandit", tuple(found), complete, LIMITS)


class World:
    """A project with a source, plus ways to run the stub executor and ingest scans."""

    def __init__(self, e: Env) -> None:
        self.e = e
        self.owner, self.s = user(e)
        self.s_, self.pid, self.plan = project(e, {"a.py": "x = 1\n"}, BANDIT, s=self.s)
        self.source = str(sql(e, "SELECT id FROM public.project_sources WHERE project_id = %s", self.pid)[0][0])  # fmt: skip

    def run(self) -> tuple[uuid.UUID, uuid.UUID]:
        run_id = start(self.s, self.pid, self.plan).json()["id"]
        deliver(self.e)
        res = sql(self.e, "SELECT id FROM public.test_results WHERE run_id = %s", run_id)[0][0]
        return uuid.UUID(run_id), uuid.UUID(str(res))

    def ingest(self, sc: ScanOutcome, *, report: bool = True, source: str | None = None) -> tuple[uuid.UUID, svc.IngestSummary]:  # fmt: skip
        run_id, result_id = self.run()
        with factory(self.e)() as db:
            art = None
            if report:
                art = runs_repo.insert_evidence_artifact(
                    db, project_id=uuid.UUID(self.pid), run_id=run_id, result_id=result_id,
                    kind="report", storage_key=f"projects/{self.pid}/runs/{run_id}/results/{result_id}/bandit.json",
                    sha256="0" * 64, size_bytes=10, content_type="application/json", filename="bandit.json",
                )  # fmt: skip
            summary = svc.ingest_scan(
                db, project_id=uuid.UUID(self.pid), run_id=run_id, result_id=result_id,
                source_id=uuid.UUID(source or self.source), scan=sc, report_artifact_id=art,
            )  # fmt: skip
            db.commit()
        return run_id, summary

    def rows(self) -> dict[str, tuple]:
        q = "SELECT fingerprint, status, verification_state, occurrences, severity, confidence, id FROM public.findings WHERE project_id = %s"  # fmt: skip
        return {r[0]: r[1:] for r in sql(self.e, q, self.pid)}

    def api(self, method: str, path: str, **kw: Any) -> Any:
        return self.s.request(method, f"{API}{path}", **kw)


@pytest.fixture
def world(make_env: Callable[..., Env]) -> World:  # noqa: F811
    return World(make_env())


# ---- ingestion ---------------------------------------------------------------------------


def test_scanner_findings_start_new_and_unverified_and_link_their_report(world: World) -> None:
    _, summary = world.ingest(scan(fr(), fr("B105", sev="low", conf="medium")))
    assert (summary.created, summary.seen_again) == (2, 0)
    rows = world.rows()
    assert {r[0:2] for r in rows.values()} == {
        ("new", "unverified")
    }  # never confirmed by a scanner
    assert {(r[3], r[4]) for r in rows.values()} == {("high", "high"), ("low", "medium")}
    for fp, row in rows.items():
        ev = sql(world.e, "SELECT count(*) FROM public.finding_evidence WHERE finding_id = %s", row[-1])[0][0]  # fmt: skip
        assert ev == 1, fp  # every finding links to the report that produced it
        assert [x[0] for x in sql(world.e, "SELECT event_type FROM public.finding_events WHERE finding_id = %s ORDER BY id", row[-1])] == ["created", "evidence_added"]  # fmt: skip
    cols = sql(world.e, "SELECT rule_id, file_path, line_number, limitations, source_id::text, category, detected_by FROM public.findings WHERE fingerprint = 'bandit:B602:a.py:0'")  # fmt: skip
    assert cols == [("B602", "a.py", 3, LIMITS, world.source, "static_analysis", "bandit")]


def test_the_same_finding_is_deduplicated_and_counted(world: World) -> None:
    world.ingest(scan(fr(line=3)))
    _, summary = world.ingest(scan(fr(line=30)))  # same issue, moved
    assert (summary.created, summary.seen_again) == (0, 1)
    ((status, _, occurrences, *_),) = world.rows().values()
    assert (status, occurrences) == ("new", 2)
    assert sql(world.e, "SELECT line_number FROM public.findings WHERE project_id = %s", world.pid) == [(30,)]  # fmt: skip
    assert (
        sql(world.e, "SELECT count(*) FROM public.finding_evidence")[0][0] == 2
    )  # one report per run


def test_rescan_verification_needs_a_complete_scan_and_never_overrides_a_person(world: World) -> None:  # fmt: skip
    world.ingest(scan(fr("B602"), fr("B301")))
    # Incomplete scan (tool errors / truncated): absence means nothing.
    _, s2 = world.ingest(scan(fr("B602"), complete=False))
    assert s2.rescan_fixed == 0 and {r[0] for r in world.rows().values()} == {"new"}
    # Complete scan without B301: a rescan attempt moves it to fixed, not to verified.
    run3, s3 = world.ingest(scan(fr("B602")))
    assert s3.rescan_fixed == 1
    fixed = world.rows()["bandit:B301:a.py:0"]
    assert fixed[0] == "fixed"
    attempts = sql(world.e, "SELECT outcome, method, run_id::text, evidence_artifact_id IS NOT NULL, created_by FROM public.verification_attempts WHERE finding_id = %s", fixed[-1])  # fmt: skip
    assert attempts == [("fixed", "rescan", str(run3), True, None)]
    # Another complete scan still without it: fixed -> verified_fixed (two independent rescans).
    _, s4 = world.ingest(scan(fr("B602")))
    assert s4.rescan_fixed == 1 and world.rows()["bandit:B301:a.py:0"][0] == "verified_fixed"
    # Reported again: reopened, and counted.
    _, s5 = world.ingest(scan(fr("B602"), fr("B301")))
    assert s5.reopened == 1
    assert world.rows()["bandit:B301:a.py:0"][0] == "reopened"
    events = [x[0] for x in sql(world.e, "SELECT event_type FROM public.finding_events WHERE finding_id = %s ORDER BY id", fixed[-1])]  # fmt: skip
    assert events.count("verification_attempt") == 2 and "reopened" in events


def test_a_scan_of_another_source_never_verifies_findings_it_did_not_cover(world: World) -> None:  # fmt: skip
    world.ingest(scan(fr("B602")))
    other = world.s.request("POST", f"{API}/projects/{world.pid}/sources/zip", params={"name": "other"}, content=__import__("support").make_zip({"b.py": "y = 2\n"}), headers={"Content-Type": "application/zip"})  # fmt: skip
    assert other.status_code == 201, other.text
    world.ingest(scan(), source=other.json()["id"])
    assert world.rows()["bandit:B602:a.py:0"][0] == "new"


def test_decisions_by_people_survive_later_scans(world: World) -> None:
    world.ingest(scan(fr("B602"), fr("B301")))
    ids = {fp: row[-1] for fp, row in world.rows().items()}
    body = {"status": "false_positive", "note": "Test fixture, not shipped"}
    assert world.api("POST", f"/findings/{ids['bandit:B602:a.py:0']}/status", json=body).status_code == 403  # fmt: skip
    admin, a = user(world.e, "admin")
    add_member(world.s, world.pid, admin, "run")
    assert a.request("POST", f"{API}/findings/{ids['bandit:B602:a.py:0']}/status", json=body).status_code == 200  # fmt: skip
    _, summary = world.ingest(scan(fr("B602")))  # reported again
    assert summary.reopened == 0
    assert world.rows()["bandit:B602:a.py:0"][0] == "false_positive"  # a person's decision stays
    assert world.rows()["bandit:B301:a.py:0"][0] == "fixed"  # absent from the scan just above
    world.ingest(scan())  # a second complete scan without either
    assert world.rows()["bandit:B602:a.py:0"][0] == "false_positive"  # still a person's call
    assert world.rows()["bandit:B301:a.py:0"][0] == "verified_fixed"


# ---- the API -----------------------------------------------------------------------------


def test_review_states_and_verification_follow_the_rules(world: World) -> None:
    world.ingest(scan(fr()))
    fid = str(next(iter(world.rows().values()))[-1])
    detail = world.api("GET", f"/findings/{fid}").json()
    assert (detail["status"], detail["verification_state"], detail["confidence"], detail["severity"]) == ("new", "unverified", "high", "high")  # fmt: skip
    assert detail["limitations"] == LIMITS and detail["file_path"] == "a.py" and len(detail["evidence"]) == 1  # fmt: skip
    assert [e["event_type"] for e in detail["events"]] == ["created", "evidence_added"]

    def status(to: str, note: str | None = None) -> Any:
        return world.api("POST", f"/findings/{fid}/status", json={"status": to, **({"note": note} if note else {})})  # fmt: skip

    assert status("verified_fixed").status_code == 422  # only a scan can verify a fix
    assert status("new").status_code == 422
    assert status("false_positive", "A long enough note").status_code == 403  # administrators only
    assert status("triaged").json()["status"] == "triaged"
    assert status("reopened").status_code == 409  # not allowed from triaged
    assert status("accepted_risk", "Accepted until Q3 rewrite lands").status_code == 403  # developers cannot accept risk  # fmt: skip
    assert status("fixed").json()["status"] == "fixed"
    assert status("reopened").json()["status"] == "reopened"

    def verify(state: str, note: str = "Reproduced by hand against a staging copy") -> Any:
        return world.api("POST", f"/findings/{fid}/verification", json={"state": state, "note": note})  # fmt: skip

    assert verify("unverified").status_code == 422 and verify("likely", "").status_code == 422
    assert verify("likely", "short").status_code == 422
    assert verify("likely").json()["verification_state"] == "likely"
    assert (
        verify("confirmed").json()["verification_state"] == "confirmed"
    )  # a person, with evidence
    events = world.api("GET", f"/findings/{fid}").json()["events"]
    assert [e["to_value"] for e in events if e["event_type"] == "verification_changed"] == ["likely", "confirmed"]  # fmt: skip
    assert len(world.e.audit("finding.status")) >= 4 and len(world.e.audit("finding.verification")) == 2  # fmt: skip


def test_a_finding_without_evidence_cannot_be_confirmed(world: World) -> None:
    world.ingest(scan(fr()), report=False)
    fid = str(next(iter(world.rows().values()))[-1])
    r = world.api("POST", f"/findings/{fid}/verification", json={"state": "confirmed", "note": "I believe it is real"})  # fmt: skip
    assert r.status_code == 409 and r.json()["error"]["code"] == "evidence_required"
    assert world.rows()["bandit:B602:a.py:0"][1] == "unverified"
    assert len(world.e.audit("finding.verification")) == 1  # the refusal is audited
    with pytest.raises(psycopg.errors.CheckViolation):  # and the database refuses it as well
        world.e.pg.execute("UPDATE public.findings SET verification_state = 'confirmed' WHERE id = %s", (fid,))  # fmt: skip
        world.e.pg.commit()
    world.e.pg.rollback()


def test_accepting_a_risk_needs_an_administrator_with_project_access(world: World) -> None:
    world.ingest(scan(fr()))
    fid = str(next(iter(world.rows().values()))[-1])
    admin, a = user(world.e, "admin")
    assert a.request("POST", f"{API}/findings/{fid}/status", json={"status": "accepted_risk", "note": "Risk accepted by owner"}).status_code == 404  # no implicit access  # fmt: skip
    add_member(world.s, world.pid, admin, "run")
    for note in ({}, {"note": "short"}):  # a note of real length is required
        r = a.request("POST", f"{API}/findings/{fid}/status", json={"status": "accepted_risk", **note})  # fmt: skip
        assert r.status_code == 422 and r.json()["error"]["code"] == "note_required"
    r = a.request("POST", f"{API}/findings/{fid}/status", json={"status": "accepted_risk", "note": "Risk accepted by owner"})  # fmt: skip
    assert r.status_code == 200 and r.json()["status"] == "accepted_risk"
    assert r.json()["events"][-1]["actor_user_id"] == admin["id"]


def test_findings_are_visible_only_through_the_project_grant(world: World) -> None:
    world.ingest(scan(fr(), fr("B105", sev="low")))
    fid = str(next(iter(world.rows().values()))[-1])
    out, o = user(world.e)
    anon = Session(world.e)
    reader, r = user(world.e)
    add_member(world.s, world.pid, reader, "read")
    paths = [f"/projects/{world.pid}/findings", f"/findings/{fid}"]
    for p in paths:
        assert world.api("GET", p).status_code == 200
        assert r.request("GET", f"{API}{p}").status_code == 200
        assert anon.request("GET", f"{API}{p}", csrf=False).status_code == 401
    assert o.request("GET", f"{API}{paths[0]}").status_code == 404
    assert o.request("GET", f"{API}{paths[1]}").status_code == 404
    for role in ("admin", "super_admin"):
        _, other = user(world.e, role)
        assert [other.request("GET", f"{API}{p}").status_code for p in paths] == [404, 404]
    # Read access can look but not change.
    for body, path in [({"status": "triaged"}, "status"), ({"state": "likely", "note": "A long enough note"}, "verification")]:  # fmt: skip
        assert r.request("POST", f"{API}/findings/{fid}/{path}", json=body).status_code == 403
        assert o.request("POST", f"{API}/findings/{fid}/{path}", json=body).status_code == 404
    assert world.rows()["bandit:B602:a.py:0"][0] == "new"
    # Filters and ordering: most severe first.
    listed = world.api("GET", f"/projects/{world.pid}/findings").json()
    assert [f["severity"] for f in listed] == ["high", "low"]
    assert [f["severity"] for f in world.api("GET", f"/projects/{world.pid}/findings", params={"severity": "low"}).json()] == ["low"]  # fmt: skip
    assert world.api("GET", f"/projects/{world.pid}/findings", params={"status": "bogus"}).status_code == 422  # fmt: skip


def test_break_glass_can_read_findings_but_not_change_them(world: World) -> None:
    world.ingest(scan(fr()))
    fid = str(next(iter(world.rows().values()))[-1])
    sup, sa = user(world.e, "super_admin")
    assert sa.request("GET", f"{API}/findings/{fid}").status_code == 404
    assert grant_bg(sa, world.pid).status_code == 201
    assert sa.request("GET", f"{API}/findings/{fid}").status_code == 200
    assert sa.request("GET", f"{API}/projects/{world.pid}/findings").status_code == 200
    assert sa.request("POST", f"{API}/findings/{fid}/status", json={"status": "triaged"}).status_code == 403  # fmt: skip
    assert sa.request("POST", f"{API}/findings/{fid}/verification", json={"state": "likely", "note": "Looking at this now"}).status_code == 403  # fmt: skip
    assert world.rows()["bandit:B602:a.py:0"][0:2] == ("new", "unverified")
    assert len(world.e.audit("breakglass.access")) >= 2


def test_no_request_can_create_a_finding(world: World) -> None:
    for method, path in [("POST", f"/projects/{world.pid}/findings"), ("PUT", f"/findings/{uuid.uuid4()}"), ("DELETE", f"/findings/{uuid.uuid4()}")]:  # fmt: skip
        assert world.api(method, path, json={"title": "x"}).status_code in {404, 405}
    assert world.rows() == {}


# ---- real Bandit in a real sandbox --------------------------------------------------------

VULN = {
    "app/__init__.py": "",
    "app/db.py": "import subprocess, pickle\nPASSWORD = 'hunter2-s3cret'\ndef run(cmd):\n    subprocess.call(cmd, shell=True)\n    return pickle.loads(cmd)\n",  # fmt: skip
    "app/ok.py": "def add(a, b):\n    return a + b\n",
}


@docker_required
def test_a_real_bandit_scan_produces_unverified_findings_with_evidence(denv: Callable[..., tuple[Env, DockerRunner]]) -> None:  # noqa: F811  # fmt: skip
    e, runner = denv(
        sandbox_allow_project_code=False, sandbox_accept_shared_kernel=False
    )  # no project-code opt-in needed
    s, pid, plan = project(e, VULN, BANDIT)
    run_id = start(s, pid, plan).json()["id"]
    assert worker(e) == ["completed"]
    (res,) = results(s, run_id)
    assert res["status"] == "failed" and "issues; each is unverified" in res["summary"]

    listed = s.request("GET", f"{API}/projects/{pid}/findings").json()
    assert {f["rule_id"] for f in listed} >= {"B602", "B301", "B105"}
    assert {(f["status"], f["verification_state"]) for f in listed} == {("new", "unverified")}
    top = listed[0]
    assert top["severity"] == "high" and top["confidence"] in {"low", "medium", "high"} and top["file_path"] == "app/db.py"  # fmt: skip
    assert top["limitations"] and "does not mean the code is secure" in top["limitations"]

    detail = s.request("GET", f"{API}/findings/{top['id']}").json()
    (ev,) = detail["evidence"]
    assert ev["filename"] == "bandit.json" and ev["run_id"] == run_id
    body = s.request("GET", f"{API}/artifacts/{ev['artifact_id']}/content")
    assert body.status_code == 200 and body.headers["content-type"].startswith("application/json")
    assert (
        b"hunter2-s3cret" not in body.content and b'"code"' not in body.content
    )  # no quoted source
    assert all(b"hunter2-s3cret" not in (f["description"] or "").encode() for f in listed)
    manifest = [x for x in s.request("GET", f"{API}/test-runs/{run_id}/results/{res['id']}").json()["evidence"] if x["name"] == "manifest.json"]  # fmt: skip
    assert manifest and runner._ids() == []

    # The same plan again: the same findings are recognised, not duplicated.
    run2 = start(s, pid, plan).json()["id"]
    worker(e)
    again = s.request("GET", f"{API}/projects/{pid}/findings").json()
    assert len(again) == len(listed) and {f["occurrences"] for f in again} == {2}
    assert {f["last_run_id"] for f in again} == {run2} and {f["first_run_id"] for f in again} == {run_id}  # fmt: skip


@docker_required
def test_clean_unreadable_and_hostile_projects(denv: Callable[..., tuple[Env, DockerRunner]]) -> None:  # noqa: F811  # fmt: skip
    # Clean: passed, and no findings.
    e, runner = denv()
    s, pid, plan = project(e, {"ok.py": "def f():\n    return 1\n"}, BANDIT)
    run_id = start(s, pid, plan).json()["id"]
    worker(e)
    (res,) = results(s, run_id)
    assert (res["status"], res["summary"]) == ("passed", "Bandit reported no issues.")
    assert s.request("GET", f"{API}/projects/{pid}/findings").json() == []

    # A file Bandit cannot parse is never a clean pass.
    e2, _ = denv()
    s2, pid2, plan2 = project(e2, {"bad.py": "def (:\n"}, BANDIT)
    run2 = start(s2, pid2, plan2).json()["id"]
    worker(e2)
    (res2,) = results(s2, run2)
    assert res2["status"] == "error" and "could not be analysed" in res2["summary"]

    # Files named like Bandit's own imports must never be loaded (python -P, no cwd on the path).
    marker = "SHADOW-EXECUTED"
    shadow = {f"{n}.py": f"print('{marker}')\nraise SystemExit(0)\n" for n in ("yaml", "bandit", "stevedore", "rich", "pygments", "json", "re", "os", "sys")}  # fmt: skip
    shadow["pkg/__init__.py"] = ""
    for name in ("yaml", "stevedore", "rich", "markdown_it", "bandit"):
        shadow[f"{name}/__init__.py"] = f"print('{marker}')\nraise SystemExit(0)\n"
    e3, runner3 = denv()
    s3, pid3, plan3 = project(e3, shadow, BANDIT)
    run3 = start(s3, pid3, plan3).json()["id"]
    worker(e3)
    (res3,) = results(s3, run3)
    assert res3["status"] in {"passed", "failed"}, res3  # Bandit ran to completion
    detail = s3.request("GET", f"{API}/test-runs/{run3}/results/{res3['id']}").json()
    for ev in detail["evidence"]:
        assert marker.encode() not in s3.request("GET", f"{API}/artifacts/{ev['id']}/content").content, ev["name"]  # fmt: skip
    assert runner3._ids() == []
