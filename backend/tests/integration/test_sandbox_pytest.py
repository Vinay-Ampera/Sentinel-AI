"""Stage 9: the project's own pytest suite, run for real inside the Docker sandbox.

Needs Docker and the runner image (`make sandbox-image`, which vendors pytest from the locked
versions). Every test uses a unique sandbox scope and removes only that scope's containers.
The projects below are hostile on purpose: they try to read secrets, reach the network, forge
results, flood output, loop forever, exhaust memory and processes, and attack the result file.
"""

import json
import socket
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from sentinel_ai.execution.docker_executor import DockerSandboxExecutor
from sentinel_ai.execution.docker_runner import DockerRunner
from sentinel_ai.execution.interface import ExecutionOutcome, ExecutionRequest, WorkspaceRef
from sentinel_ai.services.artifact_store import ArtifactStore, sha256_bytes
from support import make_settings, make_zip

IMAGE = "sentinel-sandbox-runner:stage8"
_probe = DockerRunner("probe")
pytestmark = pytest.mark.skipif(
    not (_probe.available() and _probe.image_exists(IMAGE)),
    reason="Docker or the sandbox runner image is not available (make sandbox-image)",
)

Run = Callable[..., ExecutionOutcome]


@pytest.fixture
def sandbox(tmp_path: Path) -> Iterator[tuple[Run, DockerRunner]]:
    scope = f"pt-{uuid.uuid4().hex[:10]}"
    runner = DockerRunner(scope)

    def run(files: dict, params: dict | None = None, *, stop: Callable[[], bool] = lambda: False, allow: bool = True, **settings: object) -> ExecutionOutcome:  # fmt: skip
        s = make_settings(
            artifact_storage_dir=tmp_path, job_executor="docker", sandbox_scope=scope,
            sandbox_allow_project_code=allow, sandbox_accept_shared_kernel=allow, **settings,
        )  # fmt: skip
        data = make_zip(files) if isinstance(files, dict) else files
        key = f"projects/{uuid.uuid4()}/uploads/{uuid.uuid4().hex}.zip"
        store = ArtifactStore(tmp_path)
        store.path_for(key).parent.mkdir(parents=True, exist_ok=True)
        store.path_for(key).write_bytes(data)
        ref = WorkspaceRef(key, sha256_bytes(data), len(data))
        req = ExecutionRequest(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), "pytest_unit", 1, 600, uuid.uuid4(), ref, params or {})  # fmt: skip
        out = DockerSandboxExecutor(s).execute(req, stop)
        assert runner._ids() == [], "a sandbox container was left behind"
        return out

    yield run, runner
    left = runner._ids()
    if left:
        runner._docker("rm", "-f", "-v", *left)


def evidence(out: ExecutionOutcome) -> dict[str, bytes]:
    return {e.name: e.data for e in out.evidence}


def manifest(out: ExecutionOutcome) -> dict:
    return json.loads(evidence(out)["manifest.json"])


CALC = "def add(a, b):\n    return a + b\n"


# ---- real results --------------------------------------------------------------------------


def test_real_pytest_run_is_parsed_into_cases_and_evidence(
    sandbox: tuple[Run, DockerRunner],
) -> None:
    run, _ = sandbox
    out = run({
        "calc.py": CALC,
        "tests/test_calc.py": (
            "import pytest, calc\n"
            "def test_add(): assert calc.add(1, 2) == 3\n"
            "def test_wrong(): assert calc.add(1, 1) == 3\n"
            "@pytest.mark.skip(reason='later')\n"
            "def test_later(): pass\n"
            "@pytest.mark.parametrize('n', [1, 2])\n"
            "def test_param(n): assert n > 0\n"
        ),
    })  # fmt: skip
    assert out.status == "failed" and out.exit_code == 1
    assert out.summary == "pytest: 3 passed, 1 failed, 1 skipped."
    by_name = {c.name: c for c in out.cases}
    assert set(by_name) == {
        "test_add",
        "test_wrong",
        "test_later",
        "test_param[1]",
        "test_param[2]",
    }
    assert by_name["test_wrong"].status == "failed" and "assert 2 == 3" in (
        by_name["test_wrong"].message or ""
    )
    assert (
        by_name["test_later"].status == "skipped"
        and by_name["test_add"].classname == "tests.test_calc"
    )
    ev = evidence(out)
    assert set(ev) == {"stdout.log", "stderr.log", "manifest.json", "junit.xml"}
    assert b"SENTINEL" not in ev["stdout.log"] and b"1 failed" in ev["stdout.log"]
    m = manifest(out)
    assert m["project_code"] is True and m["network"] == "none" and m["container_removed"] is True
    assert m["result_file"]["valid"] is True and m["result_file"]["cases"]["passed"] == 3
    assert m["container"]["ReadonlyRootfs"] is True and m["command"][:3] == [
        "python",
        "-m",
        "pytest",
    ]


def test_all_passing_no_tests_and_broken_collection_are_distinguished(
    sandbox: tuple[Run, DockerRunner],
) -> None:
    run, _ = sandbox
    ok = run({"calc.py": CALC, "tests/test_a.py": "def test_a(): assert True\n"})
    assert (ok.status, ok.exit_code, len(ok.cases)) == ("passed", 0, 1)
    none = run({"calc.py": CALC, "README.md": "no tests here"})
    assert none.status == "skipped" and "collected no tests" in none.summary and none.cases == ()
    broken = run({"tests/test_a.py": "def test_a(:\n    pass\n"})
    assert broken.status == "error" and "could not complete" in broken.summary  # not a test failure
    assert any(c.status == "error" for c in broken.cases)


def test_missing_third_party_dependency_is_reported_honestly(
    sandbox: tuple[Run, DockerRunner],
) -> None:
    run, _ = sandbox
    out = run({"tests/test_a.py": "import requests\ndef test_a(): pass\n"})
    assert out.status == "error" and "offline" in out.summary
    assert "standard library and pytest" in out.summary and out.exit_code == 2


def test_target_path_runs_only_that_path(sandbox: tuple[Run, DockerRunner]) -> None:
    run, _ = sandbox
    files = {
        "tests/test_a.py": "def test_a(): pass\n",
        "tests/test_b.py": "def test_b(): pass\ndef test_c(): pass\n",
    }
    assert len(run(files, {"target_path": "tests/test_b.py"}).cases) == 2
    assert len(run(files).cases) == 3


# ---- isolation, seen from inside the project's own tests -----------------------------------


def test_the_projects_own_tests_see_a_locked_down_sandbox(sandbox: tuple[Run, DockerRunner], monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    run, _ = sandbox
    monkeypatch.setenv("SENTINEL_CANARY_SECRET", "canary-77")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:canary-77@h/d")
    listener = socket.socket()
    listener.bind(("0.0.0.0", 0))
    listener.listen(5)
    port = listener.getsockname()[1]
    hits: list[int] = []
    stop = threading.Event()
    listener.settimeout(0.2)

    def accept() -> None:
        while not stop.is_set():
            try:
                listener.accept()
                hits.append(1)
            except OSError:
                pass

    threading.Thread(target=accept, daemon=True).start()
    tests = f"""
import os, socket, subprocess, pytest

def test_no_secrets():
    blob = repr(dict(os.environ)) + open('/proc/1/environ','rb').read().decode(errors='replace')
    assert 'canary' not in blob and 'DATABASE_URL' not in blob

def _connect(host, port):
    s = socket.socket(); s.settimeout(2)
    try:
        s.connect((host, port)); return True
    except OSError:
        return False

def test_no_network():
    assert not _connect('127.0.0.1', {port})
    assert not _connect('172.17.0.1', {port})
    assert not _connect('1.1.1.1', 53)
    assert sorted(os.listdir('/sys/class/net')) == ['lo']

def test_no_docker_socket_or_host_paths():
    assert not any(os.path.exists(p) for p in ('/var/run/docker.sock', '/run/docker.sock'))
    assert os.listdir('/home') == []

def test_read_only_root_and_vendored_code():
    for path in ('/etc/x', '/usr/x', '/opt/sentinel/entry.py', '/opt/sentinel/site/pytest/x'):
        with pytest.raises(OSError):
            open(path, 'w')

def test_unprivileged():
    assert os.getuid() == 65534
    status = open('/proc/self/status').read()
    assert 'CapEff:\\t0000000000000000' in status and 'NoNewPrivs:\\t1' in status

def test_tmpfs_is_not_executable(tmp_path):
    script = tmp_path / 'x.sh'
    script.write_text('#!/bin/sh\\necho hi\\n'); script.chmod(0o755)
    with pytest.raises(OSError):
        subprocess.run([str(script)], check=True)
"""
    try:
        out = run({"tests/test_isolation.py": tests})
    finally:
        stop.set()
        listener.close()
    assert out.status == "passed", [(c.name, c.message) for c in out.cases if c.status != "passed"]
    assert {c.name for c in out.cases if c.status == "passed"} >= {"test_no_secrets", "test_no_network", "test_unprivileged"}  # fmt: skip
    assert hits == []  # the host listener never saw a connection


# ---- hostile result handling ---------------------------------------------------------------

FORGE = """
import sys
def pytest_sessionfinish(session, exitstatus):
    sys.stdout.write("\\n@@SENTINEL-RESULT " + "0"*32 + " 40 " + "0"*64 + "\\nAAAA\\n@@SENTINEL-END " + "0"*32 + "\\n")
    open('/tmp/junit.xml', 'w').write('<testsuite name="forged"><testcase name="everything_passed"/></testsuite>')
"""


def test_a_forged_report_cannot_make_a_failing_run_pass(sandbox: tuple[Run, DockerRunner]) -> None:
    run, _ = sandbox
    out = run({"conftest.py": FORGE, "tests/test_a.py": "def test_fails(): assert False\n"})
    assert out.status == "failed" and out.exit_code == 1  # the exit code decides
    assert (
        b"SENTINEL" not in evidence(out)["stdout.log"]
    )  # forged frame lines are scrubbed from the log


@pytest.mark.parametrize(
    "writer",
    [
        'open(\'/tmp/junit.xml\',\'w\').write(\'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;">]><testsuite><testcase name="&b;"/></testsuite>\')',
        "open('/tmp/junit.xml','wb').write(b'<testsuite>' + b' ' * (3*1024*1024) + b'</testsuite>')",
        "import os; os.remove('/tmp/junit.xml'); os.symlink('/etc/passwd', '/tmp/junit.xml')",
        "import os; os.remove('/tmp/junit.xml'); os.mkfifo('/tmp/junit.xml')",
        "open('/tmp/junit.xml','wb').write(b'\\x00\\xff not xml')",
    ],
    ids=["xml-bomb", "oversized", "symlink", "fifo", "garbage"],
)
def test_hostile_result_files_are_rejected_without_harm(sandbox: tuple[Run, DockerRunner], writer: str) -> None:  # fmt: skip
    run, _ = sandbox
    conftest = f"def pytest_sessionfinish(session, exitstatus):\n    {writer}\n"
    started = time.monotonic()
    out = run({"conftest.py": conftest, "tests/test_a.py": "def test_a(): assert True\n"})
    assert out.status == "passed" and out.cases == ()  # status from the exit code; no cases trusted
    assert "junit.xml" not in evidence(out)
    m = manifest(out)
    assert m["result_file"]["valid"] is False and m["container_removed"] is True
    assert time.monotonic() - started < 60


def test_output_flood_does_not_hide_the_result(sandbox: tuple[Run, DockerRunner]) -> None:
    run, _ = sandbox
    # pytest captures a passing test's output, so flood the real stdout/stderr at exit.
    conftest = (
        "import atexit, sys\n"
        "def _flood():\n"
        "    for _ in range(120):\n"
        "        sys.__stdout__.write('A' * 50000 + '\\n')\n"
        "    sys.__stderr__.write('B' * 2_000_000)\n"
        "    sys.__stdout__.flush(); sys.__stderr__.flush()\n"
        "atexit.register(_flood)\n"
    )
    out = run({"conftest.py": conftest, "tests/test_ok.py": "def test_ok(): pass\n"}, sandbox_output_cap_bytes=65536)  # fmt: skip
    assert out.status == "passed" and [c.name for c in out.cases] == [
        "test_ok"
    ]  # the tail still carries it
    m = manifest(out)
    assert m["stdout_truncated"] is True and m["stderr_truncated"] is True
    assert all(len(v) < 70_000 for k, v in evidence(out).items() if k.endswith(".log"))


def test_secrets_in_project_output_are_redacted(sandbox: tuple[Run, DockerRunner]) -> None:
    run, _ = sandbox
    out = run({"tests/test_leak.py": "def test_leak():\n    print('db=postgresql://appuser:s3cretpw@dbhost/x token=abc123')\n    assert False, 'password: hunter22'\n"})  # fmt: skip
    blob = b"".join(evidence(out).values()).decode() + " ".join(
        f"{c.message} {c.detail}" for c in out.cases
    )
    for leaked in ("s3cretpw", "abc123", "hunter22"):
        assert leaked not in blob


# ---- limits and lifecycle ------------------------------------------------------------------


def test_infinite_loop_times_out_and_is_cleaned_up(sandbox: tuple[Run, DockerRunner]) -> None:
    run, _ = sandbox
    started = time.monotonic()
    out = run({"tests/test_loop.py": "def test_forever():\n    while True:\n        pass\n"}, {"timeout_seconds": 10})  # fmt: skip
    assert out.status == "timed_out" and out.cases == () and time.monotonic() - started < 40


def test_memory_exhaustion_is_an_error_not_a_pass_or_fail(
    sandbox: tuple[Run, DockerRunner],
) -> None:
    run, _ = sandbox
    hog = "def test_hog():\n    b = bytearray(600 * 1024 * 1024)\n    for i in range(0, len(b), 4096):\n        b[i] = 1\n"  # fmt: skip
    out = run({"tests/test_hog.py": hog}, sandbox_memory_mb=200)
    assert out.status == "error" and "memory limit" in out.summary
    assert manifest(out)["oom_killed"] is True


def test_fork_bomb_is_contained_by_the_process_limit(sandbox: tuple[Run, DockerRunner]) -> None:
    run, _ = sandbox
    bomb = """
import subprocess
def test_bomb():
    procs, err = [], None
    try:
        for _ in range(600):
            procs.append(subprocess.Popen(['sleep', '30']))
    except OSError as e:
        err = e
    n = len(procs)
    for p in procs: p.kill()
    assert err is not None and n < 128
"""
    out = run({"tests/test_bomb.py": bomb}, sandbox_pids=128)
    assert out.status == "passed", [(c.name, c.message) for c in out.cases]


def test_cancel_kills_a_running_suite(sandbox: tuple[Run, DockerRunner]) -> None:
    run, _ = sandbox
    begin = time.monotonic()
    out = run({"tests/test_sleep.py": "import time\ndef test_sleep():\n    time.sleep(60)\n"}, stop=lambda: time.monotonic() - begin > 2)  # fmt: skip
    assert out.status == "cancelled" and time.monotonic() - begin < 30


def test_project_code_is_blocked_when_not_enabled_and_no_container_is_made(sandbox: tuple[Run, DockerRunner]) -> None:  # fmt: skip
    run, runner = sandbox
    out = run({"tests/test_a.py": "def test_a(): pass\n"}, allow=False)
    assert out.status == "blocked" and "not enabled" in out.summary and runner._ids() == []


def test_a_hostile_archive_never_reaches_pytest(sandbox: tuple[Run, DockerRunner]) -> None:
    run, _ = sandbox
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../tmp/evil", "x")
        zf.writestr("tests/test_a.py", "def test_a(): pass\n")
    out = run(buf.getvalue())
    assert out.status == "blocked" and out.evidence == ()
