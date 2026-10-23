"""Stage 8 unit tests: no Docker needed. They check the container recipe, the fixed command
table, evidence redaction, the in-image archive extractor, and the executor's mapping from a
container's real exit state to a result."""

import functools
import importlib.util
import io
import stat
import uuid
import zipfile
from pathlib import Path
from types import ModuleType

import pytest
from pydantic import ValidationError

from sentinel_ai.execution import commands, evidence
from sentinel_ai.execution.docker_executor import DockerSandboxExecutor
from sentinel_ai.execution.docker_runner import SandboxResult
from sentinel_ai.execution.interface import ExecutionRequest, WorkspaceRef
from sentinel_ai.execution.sandbox_spec import SandboxLimits, SandboxSpec, create_argv
from sentinel_ai.services import check_catalog
from sentinel_ai.services.artifact_store import ArtifactStore, sha256_bytes
from support import make_settings, make_zip

REPO = Path(__file__).resolve().parents[3]


@functools.cache
def load_entry() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sandbox_entry", REPO / "sandbox" / "entry.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LIMITS = SandboxLimits(
    cpus=1.0, memory_mb=512, pids=128, workspace_mb=128, tmp_mb=16, timeout_seconds=60,
    max_extract_mb=96, max_file_mb=32, max_files=1000, max_zip_bytes=10_000_000,
    output_cap_bytes=1_000_000,
)  # fmt: skip


def spec(**over: object) -> SandboxSpec:
    base: dict = dict(
        image="sentinel-sandbox-runner:stage8", scope="default", run_id=uuid.uuid4(),
        batch_id=uuid.uuid4(), command=("python", "-I", "/opt/sentinel/smoke.py"),
        limits=LIMITS, extract_source=True,
    )  # fmt: skip
    return SandboxSpec(**{**base, **over})


# ---- the container recipe ------------------------------------------------------------------


def test_container_is_locked_down() -> None:
    s = spec()
    argv = create_argv("/usr/bin/docker", "sentinel-sbx-x", s)
    flat = " ".join(argv)
    for required in (
        "--network none", "--read-only", "--cap-drop ALL", "--security-opt no-new-privileges",
        "--user 65534:65534", "--memory 512m --memory-swap 512m", "--pids-limit 128", "--cpus 1",
        "--ipc none", "--log-driver none", "--init", "--ulimit core=0",
    ):  # fmt: skip
        assert required in flat, required
    # Nothing that widens the boundary, and nothing from the host.
    tokens = set(argv)
    for flag in (
        "--privileged", "--volume", "-v", "--mount", "--device", "--env", "-e", "--env-file",
        "--pid", "--userns", "--net", "--cap-add", "--publish", "-p", "--add-host", "--dns",
        "--security-opt=seccomp=unconfined", "--group-add", "--cgroupns", "--uts",
    ):  # fmt: skip
        assert flag not in tokens, flag
    for forbidden in ("host", "docker.sock", "unconfined", "/var/run", "/home"):
        assert forbidden not in flat, forbidden
    image = argv.index(s.image)
    assert "--" in argv[image:] and argv[argv.index("--") + 1 :] == list(s.command)
    assert argv[image + 1] == "--extract" and "--timeout" in argv
    assert [a for a in argv if a.startswith("--tmpfs")] == ["--tmpfs"] * 2
    assert any("noexec" in a and "nosuid" in a and "size=128m" in a for a in argv)
    labels = [argv[i + 1] for i, a in enumerate(argv) if a == "--label"]
    assert f"sentinel.sandbox.batch={s.batch_id}" in labels and "sentinel.sandbox=1" in labels


def test_runtime_is_optional_and_validated() -> None:
    assert "--runtime" not in create_argv("docker", "n", spec())
    argv = create_argv("docker", "n", spec(runtime="runsc"))
    assert argv[argv.index("--runtime") + 1] == "runsc"
    for bad in ("runsc --privileged", "a b", "../x", ""):
        with pytest.raises(ValueError):
            create_argv("docker", "n", spec(runtime=bad))


@pytest.mark.parametrize(
    "bad",
    [
        {"image": "evil image"},
        {"image": "Sentinel"},
        {"image": "x --privileged"},
        {"scope": "a b"},
        {"scope": "a=b"},
        {"command": ()},
        {"command": ("python", "")},
        {"command": ("python", "a\x00b")},
        {"limits": SandboxLimits(**{**LIMITS.__dict__, "memory_mb": 100})},  # tmpfs >= memory
        {"limits": SandboxLimits(**{**LIMITS.__dict__, "pids": 0})},
    ],
)
def test_invalid_specs_never_reach_docker(bad: dict) -> None:
    with pytest.raises(ValueError):
        create_argv("docker", "n", spec(**bad))


def test_only_the_smoke_check_has_a_runner_and_it_never_comes_from_input() -> None:
    assert set(commands.COMMANDS) == {"sandbox_smoke"}
    assert commands.lookup("pytest_unit") is None and commands.lookup("; rm -rf /") is None
    smoke = commands.lookup("sandbox_smoke")
    assert smoke and not smoke.needs_network and smoke.argv[:2] == ("python", "-I")


def test_sandbox_settings_are_validated() -> None:
    s = make_settings()
    assert (s.sandbox_cpus, s.sandbox_memory_mb, s.sandbox_pids, s.sandbox_workspace_mb) == (
        1.0,
        512,
        128,
        128,
    )
    assert s.job_executor == "stub"  # sandbox execution is an explicit opt-in
    for bad in (
        {"sandbox_image": "x --privileged"},
        {"sandbox_runtime": "a b"},
        {"sandbox_scope": "a b"},
        {"sandbox_max_extract_mb": 500},
        {"sandbox_memory_mb": 100},
        {"sandbox_cpus": 0},
        {"sandbox_max_file_mb": 97},
    ):
        with pytest.raises(ValidationError):
            make_settings(**bad)


# ---- evidence ------------------------------------------------------------------------------


def test_evidence_is_redacted_capped_and_cleaned() -> None:
    s = make_settings(redis_url="redis://:redispw-9876@cache:6379/0")
    secrets = evidence.secret_values(s)
    assert "s3cretpw" in secrets and "redispw-9876" in secrets and evidence.REDACTED not in secrets
    raw = (
        b"db=postgresql://appuser:s3cretpw@dbhost:5432/x token=abc123XYZ Bearer abcdefgh12345 "
        b"password: hunter22 \x1b[31mred\x1b[0m \x00nul\n-----BEGIN RSA PRIVATE KEY-----\nMIIB\n-----END RSA PRIVATE KEY-----"
    )
    out = evidence.redact(raw, secrets).decode()
    for leaked in ("s3cretpw", "abc123XYZ", "abcdefgh12345", "hunter22", "MIIB", "\x1b", "\x00"):
        assert leaked not in out
    assert out.count(evidence.REDACTED) >= 5 and "red" in out
    item = evidence.log_item("stdout.log", b"x" * 5000, secrets, 100, False)
    assert len(item.data) < 160 and item.data.endswith(b"[output truncated by Sentinel]\n")
    assert item.kind == "log" and item.name == "stdout.log"
    assert evidence.redact(b"\xff\xfe binary", secrets)  # invalid UTF-8 is replaced, not fatal


# ---- the in-image extractor (pure Python, run here on synthetic archives) ------------------


def _zip(entries: list[tuple[str, bytes, int | None]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data, mode in entries:
            info = zipfile.ZipInfo(name)
            if mode is not None:
                info.external_attr = mode << 16
            zf.writestr(info, data)
    return buf.getvalue()


def _extract(tmp_path: Path, data: bytes, **limits: int) -> None:
    entry = load_entry()
    tmp_path.mkdir(parents=True, exist_ok=True)
    entry.SOURCE = str(tmp_path / "src")
    path = tmp_path / "a.zip"
    path.write_bytes(data)
    args = {"max_files": 100, "max_total": 1 << 20, "max_file": 1 << 20, **limits}
    entry.extract(str(path), args["max_files"], args["max_total"], args["max_file"])


def test_extractor_accepts_a_normal_archive(tmp_path: Path) -> None:
    _extract(tmp_path, make_zip({"app/main.py": "print(1)", "README.md": "hi"}))
    assert (tmp_path / "src" / "app" / "main.py").read_text() == "print(1)"
    mode = stat.S_IMODE((tmp_path / "src" / "README.md").stat().st_mode)
    assert mode == 0o600


@pytest.mark.parametrize(
    "entries, why",
    [
        ([("../evil.txt", b"x", None)], "traversal"),
        ([("a/../../evil.txt", b"x", None)], "nested traversal"),
        ([("/etc/passwd", b"x", None)], "absolute"),
        ([("C:/x", b"x", None)], "drive letter"),
        ([("a\\b", b"x", None)], "backslash"),
        ([("a\x01b", b"x", None)], "control char"),
        ([("link", b"/etc/passwd", stat.S_IFLNK | 0o777)], "symlink"),
        ([("dev", b"", stat.S_IFCHR | 0o666)], "device"),
        ([("a", b"1", None), ("a", b"2", None)], "duplicate"),
        ([("/".join(["d"] * 40) + "/f", b"x", None)], "too deep"),
    ],
)
@pytest.mark.filterwarnings("ignore:Duplicate name")
def test_extractor_rejects_hostile_entries(tmp_path: Path, entries: list, why: str) -> None:
    entry = load_entry()
    with pytest.raises(entry.Rejected):
        _extract(tmp_path, _zip(entries))
    assert not (tmp_path.parent / "evil.txt").exists()


def test_extractor_enforces_real_sizes_not_header_claims(tmp_path: Path) -> None:
    entry = load_entry()
    with pytest.raises(entry.Rejected):
        _extract(tmp_path, make_zip({"big.bin": b"\0" * 300_000}), max_file=100_000)
    with pytest.raises(entry.Rejected):
        _extract(
            tmp_path / "2", make_zip({f"f{i}": b"x" * 1000 for i in range(50)}), max_total=20_000
        )
    with pytest.raises(entry.Rejected):
        _extract(tmp_path / "3", make_zip({f"f{i}": b"x" for i in range(30)}), max_files=10)
    with pytest.raises(entry.Rejected):
        _extract(tmp_path / "4", b"this is not a zip")


def test_extractor_never_follows_a_planted_symlink(tmp_path: Path) -> None:
    entry = load_entry()
    (tmp_path / "src").mkdir()
    outside = tmp_path / "outside.txt"
    (tmp_path / "src" / "f").symlink_to(outside)
    with pytest.raises((OSError, entry.Rejected)):  # realpath check, then O_NOFOLLOW | O_EXCL
        _extract(tmp_path, make_zip({"f": "overwrite"}))
    assert not outside.exists() and entry is not None


# ---- the executor, with a fake runner ------------------------------------------------------


class FakeRunner:
    def __init__(self, result: SandboxResult) -> None:
        self.result = result
        self.calls: list[tuple[SandboxSpec, bytes | None]] = []
        self.cleaned: list[uuid.UUID] = []

    def run(self, spec: SandboxSpec, stdin: bytes | None, should_stop: object) -> SandboxResult:
        self.calls.append((spec, stdin))
        return self.result

    def cleanup_batch(self, batch_id: uuid.UUID) -> bool:
        self.cleaned.append(batch_id)
        return True

    def sweep(self, _age: float) -> int:
        return 2


def _executor(tmp_path: Path, result: SandboxResult, **settings: object) -> tuple[DockerSandboxExecutor, FakeRunner, WorkspaceRef]:  # fmt: skip
    s = make_settings(artifact_storage_dir=tmp_path, **settings)
    runner = FakeRunner(result)
    data = make_zip({"app/main.py": "print(1)"})
    store = ArtifactStore(tmp_path)
    key = f"projects/{uuid.uuid4()}/uploads/a.zip"
    store.path_for(key).parent.mkdir(parents=True)
    store.path_for(key).write_bytes(data)
    ref = WorkspaceRef(key, sha256_bytes(data), len(data))
    return DockerSandboxExecutor(s, runner), runner, ref  # type: ignore[arg-type]


def _req(ref: WorkspaceRef | None, check: str = "sandbox_smoke") -> ExecutionRequest:
    return ExecutionRequest(
        uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), check, 1, 600, uuid.uuid4(), ref
    )


@pytest.mark.parametrize(
    "result, status",
    [
        (SandboxResult(started=True, exit_code=0), "passed"),
        (SandboxResult(started=True, exit_code=3), "failed"),
        (SandboxResult(started=True, exit_code=70), "error"),
        (SandboxResult(started=True, exit_code=137, oom_killed=True), "error"),
        (SandboxResult(started=True, exit_code=124, timed_out=True), "timed_out"),
        (SandboxResult(started=True, exit_code=137, cancelled=True), "cancelled"),
        (
            SandboxResult(start_error="the sandbox container could not be created"),
            "failed_to_start",
        ),
    ],
)
def test_result_comes_from_the_containers_real_exit_state(tmp_path: Path, result: SandboxResult, status: str) -> None:  # fmt: skip
    executor, runner, ref = _executor(tmp_path, result)
    out = executor.execute(_req(ref), lambda: False)
    assert out.status == status
    assert {e.name for e in out.evidence} == {"stdout.log", "stderr.log", "manifest.json"}
    ((spec, stdin),) = runner.calls
    assert stdin == (tmp_path / ref.storage_key).read_bytes()  # exactly the verified bytes
    assert spec.limits.timeout_seconds == 300 and spec.command == commands.COMMANDS["sandbox_smoke"].argv  # fmt: skip


def test_executor_output_cannot_forge_a_result(tmp_path: Path) -> None:
    lying = SandboxResult(started=True, exit_code=1, stdout=b'{"status": "passed", "exit_code": 0}')
    executor, _, ref = _executor(tmp_path, lying)
    assert executor.execute(_req(ref), lambda: False).status == "failed"


def test_nothing_starts_for_unknown_unsupported_or_unverified_work(tmp_path: Path) -> None:
    executor, runner, ref = _executor(tmp_path, SandboxResult(started=True, exit_code=0))
    assert executor.execute(_req(ref, "pytest_unit"), lambda: False).status == "skipped"
    assert executor.execute(_req(ref, "rm -rf /"), lambda: False).status == "skipped"
    assert executor.execute(_req(None), lambda: False).status == "blocked"  # no workspace
    assert executor.execute(_req(ref), lambda: True).status == "cancelled"  # stop before start
    bad_hash = WorkspaceRef(ref.storage_key, "0" * 64, ref.size_bytes)
    out = executor.execute(_req(bad_hash), lambda: False)
    assert out.status == "blocked" and "hash" in out.summary
    escape = WorkspaceRef("../../etc/passwd", "0" * 64, 10)
    assert executor.execute(_req(escape), lambda: False).status == "blocked"
    huge = WorkspaceRef(ref.storage_key, ref.sha256, 10**12)
    assert executor.execute(_req(huge), lambda: False).status == "blocked"
    assert runner.calls == []  # no container was ever created for any of the above


def test_hostile_archive_is_blocked_on_the_host_before_any_container(tmp_path: Path) -> None:
    executor, runner, _ = _executor(tmp_path, SandboxResult(started=True, exit_code=0))
    for name, data in {
        "traversal": _zip([("../evil", b"x", None)]),
        "bomb": make_zip({"z.bin": b"\0" * 50_000_000}),
        "garbage": b"not a zip at all",
    }.items():
        key = f"projects/{uuid.uuid4()}/uploads/{name}.zip"
        store = ArtifactStore(tmp_path)
        store.path_for(key).parent.mkdir(parents=True, exist_ok=True)
        store.path_for(key).write_bytes(data)
        out = executor.execute(
            _req(WorkspaceRef(key, sha256_bytes(data), len(data))), lambda: False
        )
        assert out.status == "blocked", name
    assert runner.calls == []


def test_evidence_redacts_configured_secrets_and_records_the_limits(tmp_path: Path) -> None:
    leak = SandboxResult(started=True, exit_code=0, stdout=b"url=postgresql://appuser:s3cretpw@h/d")
    executor, _, ref = _executor(tmp_path, leak)
    out = executor.execute(_req(ref), lambda: False)
    by_name = {e.name: e for e in out.evidence}
    assert b"s3cretpw" not in by_name["stdout.log"].data
    manifest = by_name["manifest.json"].data.decode()
    assert '"network": "none"' in manifest and '"memory_mb": 512' in manifest


def test_terminate_and_sweep_delegate_to_the_runner(tmp_path: Path) -> None:
    executor, runner, _ = _executor(tmp_path, SandboxResult())
    batch = uuid.uuid4()
    assert executor.terminate(batch) is True and runner.cleaned == [batch]
    assert executor.sweep() == 2


# ---- catalog -------------------------------------------------------------------------------


def test_sandbox_smoke_is_developer_selectable_only() -> None:
    spec_ = check_catalog.CATALOG["sandbox_smoke"]
    assert spec_.base_risk == "low" and spec_.developer_selectable and not spec_.automatic
    assert not spec_.always_requires_approval
    assert "sandbox_smoke" not in check_catalog.match_prompt("run the sandbox smoke test please")
