"""Stage 10 integration: findings from several scanners, normalization and de-duplication.

Needs a disposable database (TEST_DATABASE_URL ending _test). Scanner outcomes are built
directly (no Docker): what is tested is ingestion, grouping and the API, not the scanners.
"""

from test_findings import World, scan, world  # noqa: F401 (world is a fixture)
from test_plans_api import API
from test_runs_jobs import make_env  # noqa: F401 (fixture used by ``world``)

from sentinel_ai.execution.interface import FindingResult, ScanOutcome
from sentinel_ai.services import findings as svc


def sast(tool: str, rule: str, line: int, cwe: int | None = 78, path: str = "a.py") -> FindingResult:  # fmt: skip
    return FindingResult(tool, rule, f"{rule}: finding", "high", "medium", path, line, "message", f"{tool}:{rule}:{path}:{line}", cwe)  # fmt: skip


def dep(advisory: str, aliases: tuple[str, ...], component: str = "pypi:django@3.0.0") -> FindingResult:  # fmt: skip
    return FindingResult("dependency_audit", advisory, f"django 3.0.0: {advisory}", "high", "high", "poetry.lock", None, "Fixed in: 3.0.1.", f"dependency_audit:{advisory}", 79, "dependency", component, aliases)  # fmt: skip


def zap(rule: str = "10038-1") -> FindingResult:
    return FindingResult("zap", rule, "CSP header not set", "medium", "high", "/login", None, "m", f"zap:{rule}", 693, "dynamic", "GET https://app.example.com/login")  # fmt: skip


def outcome(tool: str, *found: FindingResult, complete: bool = True) -> ScanOutcome:
    return ScanOutcome(tool, tuple(found), complete, "limits")


def test_findings_from_two_tools_are_grouped_but_each_keeps_its_tool_and_evidence(world: World) -> None:  # noqa: F811  # fmt: skip
    world.ingest(scan(sast("bandit", "B602", 3)))
    world.ingest(outcome("semgrep", sast("semgrep", "sentinel.python.subprocess-shell-true", 4)))
    rows = world.e.pg.execute("SELECT detected_by, group_id, status, verification_state, (SELECT count(*) FROM public.finding_evidence fe WHERE fe.finding_id = f.id) FROM public.findings f WHERE project_id = %s ORDER BY detected_by", (world.pid,)).fetchall()  # fmt: skip
    assert [r[0] for r in rows] == ["bandit", "semgrep"] and rows[0][1] is not None and rows[0][1] == rows[1][1]  # fmt: skip
    assert all(r[2:] == ("new", "unverified", 1) for r in rows)  # nothing merged, none confirmed

    groups = world.api("GET", f"/projects/{world.pid}/finding-groups").json()
    assert len(groups) == 1 and groups[0]["kind"] == "location" and groups[0]["tools"] == ["bandit", "semgrep"]  # fmt: skip
    assert {m["detected_by"] for m in groups[0]["members"]} == {"bandit", "semgrep"}
    listed = world.api("GET", f"/projects/{world.pid}/findings").json()
    assert {f["group_id"] for f in listed} == {groups[0]["id"]} and {f["cwe"] for f in listed} == {78}  # fmt: skip
    detail = world.api("GET", f"/findings/{listed[0]['id']}").json()
    assert [r["detected_by"] for r in detail["related"]] != [detail["detected_by"]]
    assert len(detail["related"]) == 1 and len(detail["evidence"]) == 1


def test_one_tool_does_not_verify_or_touch_another_tools_findings(world: World) -> None:  # noqa: F811
    world.ingest(scan(sast("bandit", "B602", 3)))
    world.ingest(outcome("semgrep", sast("semgrep", "sentinel.python.eval-exec", 40, cwe=95)))
    # A complete Semgrep scan that no longer reports its finding fixes only that one.
    _, summary = world.ingest(outcome("semgrep"))
    assert summary.rescan_fixed == 1
    states = dict(world.e.pg.execute("SELECT detected_by, status FROM public.findings WHERE project_id = %s", (world.pid,)).fetchall())  # fmt: skip
    assert states == {"bandit": "new", "semgrep": "fixed"}


def test_a_person_decision_survives_regrouping(world: World) -> None:  # noqa: F811
    world.ingest(scan(sast("bandit", "B602", 3)))
    fid = world.api("GET", f"/projects/{world.pid}/findings").json()[0]["id"]
    assert world.api("POST", f"/findings/{fid}/status", json={"status": "triaged"}).status_code == 200  # fmt: skip
    world.ingest(outcome("semgrep", sast("semgrep", "r", 5)))
    row = world.e.pg.execute("SELECT status, group_id FROM public.findings WHERE id = %s", (fid,)).fetchone()  # fmt: skip
    assert row and row[0] == "triaged" and row[1] is not None


def test_dependency_findings_store_component_aliases_and_no_line(world: World) -> None:  # noqa: F811
    world.ingest(outcome("dependency_audit", dep("PYSEC-1", ("PYSEC-1", "CVE-1")), dep("GHSA-1", ("GHSA-1", "CVE-1")), dep("PYSEC-9", ("PYSEC-9",))))  # fmt: skip
    rows = world.e.pg.execute("SELECT rule_id, category, component, aliases, line_number, cwe, group_id FROM public.findings WHERE project_id = %s ORDER BY rule_id", (world.pid,)).fetchall()  # fmt: skip
    by_rule = {r[0]: r for r in rows}
    assert by_rule["PYSEC-1"][1:6] == ("dependency", "pypi:django@3.0.0", ["PYSEC-1", "CVE-1"], None, 79)  # fmt: skip
    assert by_rule["PYSEC-1"][6] is not None and by_rule["PYSEC-1"][6] == by_rule["GHSA-1"][6]
    assert by_rule["PYSEC-9"][6] is None  # shares no alias: stays on its own
    groups = world.api("GET", f"/projects/{world.pid}/finding-groups").json()
    assert len(groups) == 1 and groups[0]["kind"] == "advisory" and len(groups[0]["members"]) == 2


def test_an_unfixed_dependency_stays_open_and_a_fixed_one_is_verified_by_a_complete_rescan(world: World) -> None:  # noqa: F811  # fmt: skip
    world.ingest(outcome("dependency_audit", dep("PYSEC-1", ("PYSEC-1",))))
    _, summary = world.ingest(outcome("dependency_audit", complete=False))  # unsupported lockfile
    assert summary.rescan_fixed == 0
    _, summary = world.ingest(outcome("dependency_audit"))
    assert summary.rescan_fixed == 1
    assert world.e.pg.execute("SELECT status FROM public.findings WHERE project_id = %s", (world.pid,)).fetchone() == ("fixed",)  # fmt: skip


def test_dynamic_findings_never_verify_as_gone_and_are_not_grouped_with_static_ones(world: World) -> None:  # noqa: F811  # fmt: skip
    world.ingest(outcome("zap", zap(), complete=False))
    world.ingest(scan(sast("bandit", "B602", 3, cwe=693)))
    world.ingest(outcome("zap", complete=False))  # ZAP scans are always incomplete
    rows = world.e.pg.execute("SELECT detected_by, status, group_id, category FROM public.findings WHERE project_id = %s ORDER BY detected_by", (world.pid,)).fetchall()  # fmt: skip
    assert rows == [("bandit", "new", None, "static_analysis"), ("zap", "new", None, "dynamic")]


def test_groups_are_project_scoped_and_need_read_access(world: World) -> None:  # noqa: F811
    world.ingest(scan(sast("bandit", "B602", 3)))
    world.ingest(outcome("semgrep", sast("semgrep", "r", 4)))
    assert world.api("GET", f"/projects/{world.pid}/finding-groups").status_code == 200
    other = world.api("GET", f"/projects/{'00000000-0000-4000-8000-000000000000'}/finding-groups")
    assert other.status_code in (403, 404)
    assert svc is not None and API
