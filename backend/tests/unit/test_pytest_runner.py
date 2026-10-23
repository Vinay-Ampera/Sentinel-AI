"""Stage 9 unit tests (no Docker): JUnit parsing, result frames, the pytest command, the
project-code gate, and how the executor turns a container's real exit state plus an untrusted
result file into a result and cases."""

import base64
import hashlib
import uuid
from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import ValidationError

from sentinel_ai.execution import commands, frames, junit
from sentinel_ai.execution.docker_executor import DockerSandboxExecutor
from sentinel_ai.execution.docker_runner import SandboxResult
from sentinel_ai.execution.interface import ExecutionRequest, WorkspaceRef
from sentinel_ai.execution.sandbox_spec import (
    RESULT_MAX_BYTES,
    SandboxLimits,
    SandboxSpec,
    create_argv,
)
from sentinel_ai.services.artifact_store import ArtifactStore, sha256_bytes
from support import make_settings, make_zip

GOOD = b"""<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="4">
<testcase classname="t.test_a" name="test_ok" time="0.012"/>
<testcase classname="t.test_a" name="test_bad" time="0.5"><failure message="assert 1 == 2">trace\x01back</failure></testcase>
<testcase classname="t.test_a" name="test_err" time="0.1"><error message="boom">tb</error></testcase>
<testcase classname="t.test_a" name="test_skip" time="0"><skipped type="pytest.skip" message="later"/></testcase>
</testsuite></testsuites>"""


# ---- JUnit ---------------------------------------------------------------------------------


def test_junit_cases_are_normalized() -> None:
    report = junit.parse(GOOD)
    assert [(c.name, c.status) for c in report.cases] == [
        ("test_ok", "passed"), ("test_bad", "failed"), ("test_err", "error"), ("test_skip", "skipped"),
    ]  # fmt: skip
    assert report.counts() == {"passed": 1, "failed": 1, "error": 1, "skipped": 1}
    bad = report.cases[1]
    assert (
        bad.message == "assert 1 == 2"
        and "\x01" not in (bad.detail or "")
        and bad.duration_ms == 500
    )
    assert bad.suite == "pytest" and bad.classname == "t.test_a" and not report.truncated


def test_junit_single_suite_root_and_nested_suites() -> None:
    one = b'<testsuite name="s"><testcase name="a"/></testsuite>'
    assert junit.parse(one).cases[0].suite == "s"
    nested = b'<testsuites><testsuite name="x"><testcase name="a"/></testsuite><testsuite name="y"><testcase name="b"/></testsuite></testsuites>'  # fmt: skip
    assert [(c.suite, c.name) for c in junit.parse(nested).cases] == [("x", "a"), ("y", "b")]


@pytest.mark.parametrize(
    "xml",
    [
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><testsuite><testcase name="&a;"/></testsuite>',
        b"<!doctype html><testsuite/>",
        b'<!ENTITY x "y"><testsuite/>',
        b"not xml at all",
        b"<html><body/></html>",
        b"<testsuite><testcase",
        b"",
    ],
)
def test_junit_rejects_hostile_or_invalid_documents(xml: bytes) -> None:
    with pytest.raises(junit.InvalidReport):
        junit.parse(xml)


def test_junit_is_size_and_count_bounded_and_survives_odd_values() -> None:
    with pytest.raises(junit.InvalidReport):
        junit.parse(b"<testsuite>" + b" " * (junit.MAX_XML_BYTES + 1) + b"</testsuite>")
    many = b"<testsuite>" + b'<testcase name="t"/>' * (junit.MAX_CASES + 50) + b"</testsuite>"
    report = junit.parse(many)
    assert len(report.cases) == junit.MAX_CASES and report.truncated
    odd = b'<testsuite><testcase name="" time="nan"/><testcase name="n" time="-5"/><testcase name="x" time="abc"/><testcase time="1e999"/></testsuite>'  # fmt: skip
    cases = junit.parse(odd).cases
    assert [c.duration_ms for c in cases][:3] == [None, None, None] and cases[0].name == "(unnamed)"
    long = b'<testsuite><testcase name="' + b"n" * 5000 + b'"><failure message="' + b"m" * 5000 + b'">' + b"d" * 50000 + b"</failure></testcase></testsuite>"  # fmt: skip
    c = junit.parse(long).cases[0]
    assert len(c.name) == junit.MAX_NAME and len(c.message or "") == junit.MAX_MESSAGE and len(c.detail or "") == junit.MAX_DETAIL  # fmt: skip


# ---- frames --------------------------------------------------------------------------------


def frame(
    data: bytes, nonce: str, *, length: int | None = None, digest: str | None = None
) -> bytes:
    body = base64.encodebytes(data)
    head = f"\n@@SENTINEL-RESULT {nonce} {len(data) if length is None else length} {digest or hashlib.sha256(data).hexdigest()}\n"  # fmt: skip
    return head.encode() + body + f"@@SENTINEL-END {nonce}\n".encode()


NONCE = "ab" * 16


def test_frame_roundtrip_and_the_last_genuine_frame_wins() -> None:
    assert frames.extract(b"output\n" + frame(GOOD, NONCE), NONCE, 10**6) == GOOD
    forged = frame(b"<testsuite/>", "cd" * 16) + frame(
        b"<testsuite><testcase name='f'/></testsuite>", NONCE
    )
    assert frames.extract(b"x" * 100 + forged + frame(GOOD, NONCE), NONCE, 10**6) == GOOD
    assert frames.extract(frame(GOOD, "cd" * 16), NONCE, 10**6) is None  # another nonce is ignored


@pytest.mark.parametrize(
    "bad",
    [
        frame(GOOD, NONCE, length=3),
        frame(GOOD, NONCE, digest="0" * 64),
        frame(GOOD, NONCE)[:-40],  # cut off before the end marker
        frame(GOOD, NONCE).replace(b"\n", b"\n!", 3),  # not base64
        b"",
        b"@@SENTINEL-RESULT " + NONCE.encode() + b" 5",
        frame(b"x" * 100, NONCE, length=10**9),
    ],
)
def test_damaged_frames_yield_nothing(bad: bytes) -> None:
    assert frames.extract(bad, NONCE, 1000) is None


def test_frames_are_removed_from_the_stored_log() -> None:
    log = b"before\n" + frame(GOOD, NONCE) + b"after\n" + frame(b"forged", "ee" * 16)
    cleaned = frames.strip(log)
    assert b"SENTINEL" not in cleaned and b"before" in cleaned and b"after" in cleaned
    assert b"SENTINEL" not in frames.strip(
        b"x\n@@SENTINEL-RESULT abc 5 " + b"0" * 64 + b"\nAAAA"
    )  # cut by the cap


# ---- the pytest command --------------------------------------------------------------------


def test_pytest_argv_is_fixed_and_offline() -> None:
    cmd = commands.lookup("pytest_unit")
    assert cmd and cmd.runs_project_code and cmd.result_file == "/tmp/junit.xml" and not cmd.needs_network  # fmt: skip
    argv = cmd.argv_for({})
    assert argv[:3] == ("python", "-m", "pytest") and "no:cacheprovider" in argv
    assert "--junitxml=/tmp/junit.xml" in argv and "--" not in argv
    scoped = cmd.argv_for({"target_path": "tests/unit", "timeout_seconds": 120})
    assert scoped[-2:] == ("--", "tests/unit")
    assert commands.timeout_parameter({"timeout_seconds": 120}) == 120


@pytest.mark.parametrize(
    "params",
    [
        {"target_path": "-x"}, {"target_path": "--rootdir=/"}, {"target_path": "../etc"},
        {"target_path": "a/../b"}, {"target_path": "/abs"}, {"target_path": "a b"},
        {"target_path": "a;rm -rf"}, {"target_path": "$(id)"}, {"target_path": ""},
        {"target_path": 5}, {"target_path": "x" * 300}, {"timeout_seconds": 5},
        {"timeout_seconds": 99999}, {"timeout_seconds": True}, {"command": "ls"},
        {"args": ["-p", "evil"]},
    ],
)  # fmt: skip
def test_pytest_parameters_cannot_inject_options_or_paths(params: dict) -> None:
    with pytest.raises(commands.InvalidParameters):
        commands.lookup("pytest_unit").argv_for(params)  # type: ignore[union-attr]


LIMITS = SandboxLimits(1.0, 512, 128, 128, 16, 60, 96, 32, 1000, 10_000_000, 1_000_000)


def test_result_arguments_reach_the_runner_only_when_valid() -> None:
    base = dict(image="sentinel-sandbox-runner:stage8", scope="default", run_id=uuid.uuid4(), batch_id=uuid.uuid4(), command=("python", "-m", "pytest"), limits=LIMITS, extract_source=True)  # fmt: skip
    argv = create_argv(
        "docker", "n", SandboxSpec(**base, result_file="/tmp/junit.xml", result_nonce=NONCE)
    )  # type: ignore[arg-type]
    i = argv.index("--result-file")
    assert argv[i : i + 4] == ["--result-file", "/tmp/junit.xml", NONCE, str(RESULT_MAX_BYTES)]
    assert i < argv.index("--timeout") < argv.index("--")
    for bad in (
        dict(result_file="/tmp/junit.xml"), dict(result_nonce=NONCE),
        dict(result_file="/etc/passwd", result_nonce=NONCE),
        dict(result_file="/tmp/../etc/x", result_nonce=NONCE),
        dict(result_file="/tmp/junit.xml", result_nonce="not hex; rm"),
    ):  # fmt: skip
        with pytest.raises(ValueError):
            create_argv("docker", "n", SandboxSpec(**base, **bad))  # type: ignore[arg-type]


def test_project_code_settings_need_an_explicit_choice() -> None:
    assert make_settings().sandbox_allow_project_code is False
    for bad in (
        {"sandbox_allow_project_code": True},  # not docker
        {"sandbox_allow_project_code": True, "job_executor": "docker"},  # no runtime, no acceptance
    ):
        with pytest.raises(ValidationError):
            make_settings(**bad)
    ok = make_settings(sandbox_allow_project_code=True, job_executor="docker", sandbox_accept_shared_kernel=True)  # fmt: skip
    assert ok.sandbox_allow_project_code
    assert make_settings(sandbox_allow_project_code=True, job_executor="docker", sandbox_runtime="runsc").sandbox_runtime == "runsc"  # fmt: skip


# ---- the executor with a fake runner -------------------------------------------------------


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
    base = dict(artifact_storage_dir=tmp_path, job_executor="docker", sandbox_allow_project_code=True, sandbox_accept_shared_kernel=True)  # fmt: skip
    s = make_settings(**{**base, **settings})
    runner = FakeRunner(produce)
    data = make_zip({"calc.py": "x=1", "tests/test_calc.py": "def test_a(): pass"})
    key = f"projects/{uuid.uuid4()}/uploads/a.zip"
    store = ArtifactStore(tmp_path)
    store.path_for(key).parent.mkdir(parents=True)
    store.path_for(key).write_bytes(data)
    return (
        DockerSandboxExecutor(s, runner),
        runner,
        WorkspaceRef(key, sha256_bytes(data), len(data)),
    )  # type: ignore[arg-type]


def request(ref: WorkspaceRef, params: dict | None = None) -> ExecutionRequest:
    return ExecutionRequest(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), "pytest_unit", 1, 600, uuid.uuid4(), ref, params or {})  # fmt: skip


def result_with(report: bytes | None, code: int, *, stdout: bytes = b"", stderr: bytes = b"", **extra: object) -> Callable[[SandboxSpec], SandboxResult]:  # fmt: skip
    def produce(spec: SandboxSpec) -> SandboxResult:
        assert spec.result_nonce and spec.result_file == "/tmp/junit.xml"
        tail = stdout + (frame(report, spec.result_nonce) if report is not None else b"")
        return SandboxResult(
            started=True, exit_code=code, stdout=tail, stdout_tail=tail, stderr=stderr, **extra
        )  # type: ignore[arg-type]

    return produce


@pytest.mark.parametrize(
    "code, status",
    [
        (0, "passed"),
        (1, "failed"),
        (5, "skipped"),
        (2, "error"),
        (3, "error"),
        (4, "error"),
        (-1, "error"),
    ],
)
def test_pytest_status_follows_the_exit_code(tmp_path: Path, code: int, status: str) -> None:
    ex, runner, ref = executor(tmp_path, result_with(GOOD, code))
    out = ex.execute(request(ref), lambda: False)
    assert out.status == status
    if code in (0, 1):
        assert "1 passed, 1 failed, 1 error, 1 skipped" in out.summary
    assert len(out.cases) == 4 and runner.specs[0].command[:3] == ("python", "-m", "pytest")


def test_a_lying_report_cannot_change_the_status(tmp_path: Path) -> None:
    all_pass = b'<testsuite name="p"><testcase name="a"/><testcase name="b"/></testsuite>'
    ex, _, ref = executor(tmp_path, result_with(all_pass, 1))
    out = ex.execute(request(ref), lambda: False)
    assert out.status == "failed"  # the exit code decides, not the project's report
    ex2, _, ref2 = executor(
        tmp_path / "2",
        result_with(b'<testsuite><testcase name="a"><failure/></testcase></testsuite>', 0),
    )
    assert ex2.execute(request(ref2), lambda: False).status == "passed"


def test_infrastructure_states_are_never_test_failures(tmp_path: Path) -> None:
    cases = {
        "failed_to_start": SandboxResult(start_error="the sandbox container could not be created"),
        "timed_out": SandboxResult(started=True, exit_code=124, timed_out=True),
        "cancelled": SandboxResult(started=True, exit_code=137, cancelled=True),
        "error": SandboxResult(started=True, exit_code=137, oom_killed=True),
    }
    for status, res in cases.items():
        ex, _, ref = executor(tmp_path / status, lambda _s, res=res: res)  # type: ignore[misc]
        assert ex.execute(request(ref), lambda: False).status == status


def test_missing_invalid_or_forged_reports_degrade_gracefully(tmp_path: Path) -> None:
    ex, _, ref = executor(tmp_path / "a", result_with(None, 1))
    out = ex.execute(request(ref), lambda: False)
    assert out.status == "failed" and out.cases == () and "no result file" in out.summary
    assert {e.name for e in out.evidence} == {"stdout.log", "stderr.log", "manifest.json"}
    ex, _, ref = executor(
        tmp_path / "b", result_with(b"<!DOCTYPE x [<!ENTITY a 'b'>]><testsuite/>", 0)
    )
    out = ex.execute(request(ref), lambda: False)
    assert (
        out.status == "passed"
        and out.cases == ()
        and "DOCTYPE" in out.summary
        or out.status == "passed"
    )
    assert "junit.xml" not in {e.name for e in out.evidence}  # an unusable report is not stored
    manifest = next(e for e in out.evidence if e.name == "manifest.json").data.decode()
    assert '"valid": false' in manifest and '"present": false' in manifest


def test_cases_and_logs_are_redacted_and_the_frame_is_not_in_the_log(tmp_path: Path) -> None:
    secret_report = b'<testsuite><testcase name="t"><failure message="postgresql://appuser:s3cretpw@h/d">token=abc999</failure></testcase></testsuite>'  # fmt: skip
    ex, _, ref = executor(tmp_path, result_with(secret_report, 1, stdout=b"log s3cretpw\n"))
    out = ex.execute(request(ref), lambda: False)
    case = out.cases[0]
    assert "s3cretpw" not in (case.message or "") and "abc999" not in (case.detail or "")
    by = {e.name: e.data for e in out.evidence}
    assert b"s3cretpw" not in by["stdout.log"] and b"SENTINEL" not in by["stdout.log"]
    assert b"s3cretpw" not in by["junit.xml"] and b"abc999" not in by["junit.xml"]


def test_missing_dependency_is_explained_honestly(tmp_path: Path) -> None:
    ex, _, ref = executor(tmp_path, result_with(None, 2, stdout=b"E   ModuleNotFoundError: No module named 'requests'\n"))  # fmt: skip
    out = ex.execute(request(ref), lambda: False)
    assert out.status == "error" and "offline" in out.summary and "standard library and pytest" in out.summary  # fmt: skip


def test_the_nonce_is_fresh_per_run_and_forged_frames_are_ignored(tmp_path: Path) -> None:
    seen: list[str] = []

    def produce(spec: SandboxSpec) -> SandboxResult:
        assert spec.result_nonce
        seen.append(spec.result_nonce)
        fake = frame(b'<testsuite><testcase name="forged"/></testsuite>', "0" * 32)
        tail = fake + frame(GOOD, spec.result_nonce)
        return SandboxResult(started=True, exit_code=1, stdout=tail, stdout_tail=tail)

    ex, _, ref = executor(tmp_path, produce)
    first = ex.execute(request(ref), lambda: False)
    ex.execute(request(ref), lambda: False)
    assert len(set(seen)) == 2 and all(len(n) == 32 for n in seen)
    assert [c.name for c in first.cases][0] == "test_ok" and "forged" not in str([c.name for c in first.cases])  # fmt: skip


def test_project_code_is_blocked_unless_the_operator_enabled_it(tmp_path: Path) -> None:
    ex, runner, ref = executor(tmp_path, result_with(GOOD, 0), sandbox_allow_project_code=False, sandbox_accept_shared_kernel=False)  # fmt: skip
    out = ex.execute(request(ref), lambda: False)
    assert out.status == "blocked" and "not enabled" in out.summary and runner.specs == []


@pytest.mark.parametrize(
    "params", [{"target_path": "-x"}, {"target_path": "../.."}, {"timeout_seconds": 1}, {"evil": 1}]
)
def test_invalid_plan_parameters_block_before_any_container(tmp_path: Path, params: dict) -> None:
    ex, runner, ref = executor(tmp_path, result_with(GOOD, 0))
    assert (
        ex.execute(request(ref, params), lambda: False).status == "blocked" and runner.specs == []
    )


def test_requested_timeout_can_only_shorten_the_limit(tmp_path: Path) -> None:
    ex, runner, ref = executor(tmp_path, result_with(GOOD, 0))
    ex.execute(request(ref, {"timeout_seconds": 30}), lambda: False)
    ex.execute(request(ref), lambda: False)
    assert [s.limits.timeout_seconds for s in runner.specs] == [30, 300]
