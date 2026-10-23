"""Stage 10 unit tests (no Docker, no database): Bandit report parsing and normalization, the
fixed Bandit command, how the executor turns an exit state plus an untrusted report into a
result and scan, and the checks that still have no runner (load, browser). The other scanners are tested in
test_security_scanners.py."""

import json
import uuid
from collections.abc import Callable
from pathlib import Path

import pytest

from sentinel_ai.execution import bandit_report, commands, frames
from sentinel_ai.execution.docker_executor import DockerSandboxExecutor
from sentinel_ai.execution.docker_runner import SandboxResult
from sentinel_ai.execution.interface import ExecutionRequest, WorkspaceRef
from sentinel_ai.execution.sandbox_spec import SandboxSpec
from sentinel_ai.services import check_catalog
from sentinel_ai.services.artifact_store import ArtifactStore, sha256_bytes
from support import make_settings, make_zip


def item(**over: object) -> dict:
    base = {
        "code": "9 password = 'hunter2'\n",
        "filename": "./app/db.py",
        "issue_confidence": "MEDIUM",
        "issue_cwe": {"id": 259, "link": "https://cwe.mitre.org/data/definitions/259.html"},
        "issue_severity": "LOW",
        "issue_text": "Possible hardcoded password: 'hunter2'",
        "line_number": 9,
        "test_id": "B105",
        "test_name": "hardcoded_password_string",
    }
    return {**base, **over}


def report(*results: dict, errors: list | None = None) -> bytes:
    return json.dumps({"errors": errors or [], "metrics": {"_totals": {"loc": 120}}, "results": list(results)}).encode()  # fmt: skip


# ---- parsing -----------------------------------------------------------------------------


def test_findings_are_normalized_and_never_carry_code_or_the_flagged_secret() -> None:
    parsed = bandit_report.parse(report(item()))
    (f,) = parsed.findings
    assert (f.rule_id, f.severity, f.confidence, f.path, f.line, f.cwe) == ("B105", "low", "medium", "app/db.py", 9, 259)  # fmt: skip
    assert f.message == "Possible hardcoded password: '<redacted>'"
    stored = bandit_report.sanitized_report(parsed)
    assert b"hunter2" not in stored and b'"code"' not in stored
    assert json.loads(stored)["results"][0]["fingerprint"] == f.fingerprint
    assert parsed.lines_scanned == 120


def test_fingerprints_survive_line_moves_and_separate_repeated_issues() -> None:
    a = bandit_report.parse(report(item(line_number=9), item(line_number=40))).findings
    b = bandit_report.parse(report(item(line_number=19), item(line_number=60))).findings
    assert [f.fingerprint for f in a] == [f.fingerprint for f in b]  # moved, same findings
    assert a[0].fingerprint != a[1].fingerprint  # two occurrences in one file stay distinct
    other = bandit_report.parse(report(item(filename="./other.py"))).findings[0]
    assert other.fingerprint not in {f.fingerprint for f in a}
    assert all(f.fingerprint.startswith("bandit:") and len(f.fingerprint) < 100 for f in a)


@pytest.mark.parametrize("name", ["/etc/passwd", "../x.py", "a/../../b.py", "-rf.py", "a b\x00.py", "", None, 5])  # fmt: skip
def test_paths_that_could_mislead_are_not_kept(name: object) -> None:
    assert bandit_report.parse(report(item(filename=name))).findings[0].path == "(unknown)"


def test_hostile_values_are_clamped_or_dropped() -> None:
    hostile = report(
        item(test_id="B999999"),  # not a rule id
        item(test_id="rm -rf"),
        item(line_number=10**12),
        item(issue_severity="CRITICAL!!", issue_confidence=None),
        item(issue_text="x\x00\x1b[31m" + "A" * 5000),
        item(issue_cwe={"id": True}),
        "not even a dict",  # type: ignore[arg-type]
    )
    parsed = bandit_report.parse(hostile)
    assert len(parsed.findings) == 4
    assert {f.line for f in parsed.findings} == {1, 9}
    assert all(f.severity in {"low"} and f.confidence in {"low", "medium"} for f in parsed.findings)  # fmt: skip
    long = next(f for f in parsed.findings if f.message.startswith("x"))
    assert len(long.message) <= bandit_report.TEXT_LIMIT and "\x00" not in long.message
    assert all(f.cwe is None or f.cwe == 259 for f in parsed.findings)


@pytest.mark.parametrize("raw", [b"", b"nope", b"[]", b'{"results": 5}', b'{"x": 1}', b"[" * 5000])
def test_unusable_reports_are_rejected(raw: bytes) -> None:
    with pytest.raises(bandit_report.InvalidReport):
        bandit_report.parse(raw)


def test_the_number_of_findings_is_bounded() -> None:
    rows = [item(line_number=i + 1) for i in range(bandit_report.MAX_FINDINGS + 5)]
    parsed = bandit_report.parse(report(*rows))
    assert len(parsed.findings) == bandit_report.MAX_FINDINGS and parsed.truncated
    assert len({f.fingerprint for f in parsed.findings}) == bandit_report.MAX_FINDINGS


# ---- the command and the checks that have no runner --------------------------------------


def test_bandit_command_is_fixed_offline_and_never_puts_the_project_on_the_path() -> None:
    cmd = commands.lookup("bandit_static")
    assert cmd and not cmd.runs_project_code and not cmd.needs_network and cmd.kind == "bandit"
    argv = cmd.argv_for({})
    assert argv[:4] == ("python", "-P", "-m", "bandit")  # -P: no cwd on sys.path
    assert argv[argv.index("-o") + 1] == cmd.result_file == "/tmp/bandit.json"
    assert "-f" in argv and "json" in argv
    assert cmd.argv_for({"timeout_seconds": 60}) == argv


@pytest.mark.parametrize("params", [{"target_path": "x"}, {"severity": "high"}, {"args": ["--exit-zero"]}, {"timeout_seconds": 1}, {"timeout_seconds": True}])  # fmt: skip
def test_bandit_accepts_no_option_from_a_plan(params: dict) -> None:
    cmd = commands.lookup("bandit_static")
    assert cmd
    with pytest.raises(commands.InvalidParameters):
        cmd.argv_for(params)


@pytest.mark.parametrize("check_id", ["load_basic", "playwright_e2e", "js_unit", "axe_accessibility"])  # fmt: skip
def test_checks_without_a_runner_still_cannot_report_a_result(check_id: str) -> None:
    assert commands.lookup(check_id) is None


def test_intrusive_scans_always_need_approval_and_a_target() -> None:
    specs = check_catalog.CATALOG
    assert specs["zap_active"].always_requires_approval and specs["zap_active"].active_on_target
    assert specs["zap_active"].base_risk == "high" and specs["zap_active"].target_kind == "url"
    assert not specs["zap_baseline"].always_requires_approval
    assert specs["bandit_static"].target_kind != "url" and not specs["bandit_static"].active_on_target  # fmt: skip


# ---- the executor with a fake runner -----------------------------------------------------


class FakeRunner:
    def __init__(self, produce: Callable[[SandboxSpec], SandboxResult]) -> None:
        self.produce = produce
        self.specs: list[SandboxSpec] = []

    def run(self, spec: SandboxSpec, stdin: bytes | None, should_stop: object) -> SandboxResult:
        self.specs.append(spec)
        return self.produce(spec)

    def cleanup_batch(self, _b: uuid.UUID) -> bool:
        return True

    def sweep(self, _a: float) -> int:
        return 0


def executor(tmp_path: Path, produce: Callable[[SandboxSpec], SandboxResult], **settings: object) -> tuple[DockerSandboxExecutor, FakeRunner, WorkspaceRef]:  # fmt: skip
    s = make_settings(artifact_storage_dir=tmp_path, job_executor="docker", **settings)
    runner = FakeRunner(produce)
    data = make_zip({"app.py": "x = 1\n"})
    key = f"projects/{uuid.uuid4()}/uploads/a.zip"
    store = ArtifactStore(tmp_path)
    store.path_for(key).parent.mkdir(parents=True)
    store.path_for(key).write_bytes(data)
    return (
        DockerSandboxExecutor(s, runner),
        runner,
        WorkspaceRef(key, sha256_bytes(data), len(data)),
    )  # type: ignore[arg-type]


def req(ref: WorkspaceRef, check: str = "bandit_static") -> ExecutionRequest:
    return ExecutionRequest(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), check, 1, 600, uuid.uuid4(), ref, {})  # fmt: skip


def produced(raw: bytes | None, code: int, **extra: object) -> Callable[[SandboxSpec], SandboxResult]:  # fmt: skip
    def run(spec: SandboxSpec) -> SandboxResult:
        assert spec.result_nonce and spec.result_file == "/tmp/bandit.json"
        framed = b""
        if raw is not None:
            digest = __import__("hashlib").sha256(raw).hexdigest()
            b64 = __import__("base64").b64encode(raw)
            n = spec.result_nonce
            framed = f"\n@@SENTINEL-RESULT {n} {len(raw)} {digest}\n".encode() + b64 + f"\n@@SENTINEL-END {n}\n".encode()  # fmt: skip
        return SandboxResult(
            started=True, exit_code=code, stdout=framed, stdout_tail=framed, stderr=b"", **extra
        )  # type: ignore[arg-type]

    return run


def test_issues_make_a_failed_result_with_unverified_scan_findings(tmp_path: Path) -> None:
    ex, runner, ref = executor(tmp_path, produced(report(item(), item(test_id="B602", test_name="subprocess_popen_with_shell_equals_true", issue_severity="HIGH", issue_confidence="HIGH", issue_text="shell=True", line_number=3)), 1))  # fmt: skip
    out = ex.execute(req(ref), lambda: False)
    assert out.status == "failed" and "2 issues" in out.summary and "unverified" in out.summary
    assert out.scan and out.scan.tool == "bandit" and out.scan.complete and len(out.scan.findings) == 2  # fmt: skip
    assert "Static pattern match" in out.scan.limitations
    assert out.cases == () and {e.name for e in out.evidence} == {"stdout.log", "stderr.log", "manifest.json", "bandit.json"}  # fmt: skip
    assert not any(b"hunter2" in e.data for e in out.evidence)
    assert runner.specs[0].command[:4] == ("python", "-P", "-m", "bandit")


def test_a_clean_pass_needs_a_valid_report(tmp_path: Path) -> None:
    for code, raw, status in [
        (0, report(), "passed"),
        (0, None, "error"),  # exit 0 but no report: never "no issues"
        (0, b"garbage", "error"),
        (1, None, "error"),
        (2, report(), "error"),
        (-1, report(), "error"),
    ]:
        ex, _, ref = executor(tmp_path, produced(raw, code))
        out = ex.execute(req(ref), lambda: False)
        assert out.status == status, (code, raw, out)
        if status == "passed":
            assert out.scan and out.scan.findings == () and out.scan.complete
        if status == "error":
            assert out.scan is None  # a failed scan never reads as "everything is fixed"


def test_files_bandit_could_not_read_make_the_scan_incomplete(tmp_path: Path) -> None:
    broken = [{"filename": "./bad.py", "reason": "syntax error while parsing AST from file"}]
    ex, _, ref = executor(tmp_path, produced(report(errors=broken), 1))
    out = ex.execute(req(ref), lambda: False)
    assert out.status == "error" and "could not be analysed" in out.summary
    assert out.scan and not out.scan.complete  # kept, but it must not verify anything as fixed
    ex, _, ref = executor(tmp_path, produced(report(item(), errors=broken), 1))
    out = ex.execute(req(ref), lambda: False)
    assert out.status == "failed" and out.scan and not out.scan.complete


def test_a_lying_exit_code_or_forged_frame_cannot_make_a_pass(tmp_path: Path) -> None:
    assert frames.strip(b"x") == b"x"
    ex, _, ref = executor(tmp_path, lambda spec: SandboxResult(started=True, exit_code=0, stdout=b"@@SENTINEL-RESULT deadbeef 2 00\ne30=\n@@SENTINEL-END deadbeef\n", stdout_tail=b"@@SENTINEL-RESULT deadbeef 2 00\ne30=\n@@SENTINEL-END deadbeef\n", stderr=b""))  # type: ignore[arg-type]  # fmt: skip
    assert ex.execute(req(ref), lambda: False).status == "error"


def test_infrastructure_states_are_never_scan_results(tmp_path: Path) -> None:
    for extra, status in [
        ({"timed_out": True}, "timed_out"),
        ({"oom_killed": True}, "error"),
        ({"cancelled": True}, "cancelled"),
        ({"start_error": "no image"}, "failed_to_start"),
    ]:
        ex, _, ref = executor(tmp_path, produced(report(item()), 1, **extra))
        out = ex.execute(req(ref), lambda: False)
        assert out.status == status and out.scan is None


def test_static_analysis_does_not_need_the_project_code_opt_in(tmp_path: Path) -> None:
    ex, _, ref = executor(tmp_path, produced(report(), 0), sandbox_allow_project_code=False)
    assert ex.execute(req(ref), lambda: False).status == "passed"
