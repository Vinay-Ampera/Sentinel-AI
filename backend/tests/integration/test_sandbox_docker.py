"""Stage 8: the Docker sandbox, with hostile commands run in real containers.

Needs a reachable Docker daemon and the runner image (`make sandbox-image`); skipped
otherwise. Every test uses a unique scope label, and its finalizer removes only containers
carrying that label, so no other container on the daemon is ever touched. No target code is
run: the commands are test-supplied probes that try to escape or exhaust the sandbox.
"""

import json
import os
import socket
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from sentinel_ai.execution.docker_runner import DockerRunner, SandboxResult
from sentinel_ai.execution.sandbox_spec import SandboxLimits, SandboxSpec, create_argv
from support import make_zip

IMAGE = "sentinel-sandbox-runner:stage8"
_probe = DockerRunner("probe")
pytestmark = pytest.mark.skipif(
    not (_probe.available() and _probe.image_exists(IMAGE)),
    reason="Docker or the sandbox runner image is not available (make sandbox-image)",
)


@pytest.fixture
def runner() -> Iterator[DockerRunner]:
    r = DockerRunner(f"test-{uuid.uuid4().hex[:10]}")
    yield r
    leftovers = r._ids()  # only this test's scope label
    if leftovers:
        r._docker("rm", "-f", "-v", *leftovers)
    assert r._ids() == [], "test left containers behind"


def lim(**over: int | float) -> SandboxLimits:
    base: dict = dict(
        cpus=1.0, memory_mb=128, pids=64, workspace_mb=32, tmp_mb=8, timeout_seconds=20,
        max_extract_mb=16, max_file_mb=8, max_files=500, max_zip_bytes=2_000_000,
        output_cap_bytes=65536,
    )  # fmt: skip
    return SandboxLimits(**{**base, **over})


def spec_for(r: DockerRunner, command: tuple[str, ...], *, extract: bool = False, batch: uuid.UUID | None = None, **limits: int | float) -> SandboxSpec:  # fmt: skip
    return SandboxSpec(
        image=IMAGE, scope=r.scope, run_id=uuid.uuid4(), batch_id=batch or uuid.uuid4(),
        command=command, limits=lim(**limits), extract_source=extract,
    )  # fmt: skip


def go(r: DockerRunner, code: str, *, stdin: bytes | None = None, extract: bool = False, stop: Callable[[], bool] = lambda: False, **limits: int | float) -> SandboxResult:  # fmt: skip
    res = r.run(spec_for(r, ("python", "-I", "-c", code), extract=extract, **limits), stdin, stop)
    assert res.removed and r._ids() == []  # always cleaned up, whatever happened
    return res


def probe(r: DockerRunner, code: str, **limits: int | float) -> dict:
    res = go(r, code, **limits)
    assert res.exit_code == 0, res.stderr.decode()
    return json.loads(res.stdout.decode().strip().splitlines()[-1])


# ---- isolation -----------------------------------------------------------------------------


def test_no_host_secrets_reach_the_sandbox(
    runner: DockerRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in {
        "SENTINEL_CANARY_SECRET": "canary-9f3a", "DATABASE_URL": "postgresql://u:canary-9f3a@h/d",
        "REDIS_URL": "redis://:canary-9f3a@h", "SESSION_TOKEN_PEPPER": "canary-9f3a",
    }.items():  # fmt: skip
        monkeypatch.setenv(name, value)
    # A fresh runner picks up the (filtered) environment the way the worker would.
    r = DockerRunner(runner.scope)
    out = probe(r, "import os,json;print(json.dumps({'env':dict(os.environ),'pid1':open('/proc/1/environ','rb').read().decode(errors='replace')}))")  # fmt: skip
    blob = json.dumps(out)
    assert "canary" not in blob
    assert set(out["env"]) <= {"PATH", "HOME", "LANG", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "PYTEST_DISABLE_PLUGIN_AUTOLOAD"}  # fmt: skip
    assert not any(k in out["pid1"] for k in ("DATABASE", "REDIS", "PEPPER", "SECRET", "TOKEN"))


def test_network_is_disabled_for_every_route(runner: DockerRunner) -> None:
    listener = socket.socket()
    listener.bind(("0.0.0.0", 0))
    listener.listen(5)
    listener.settimeout(0.2)
    port = listener.getsockname()[1]
    accepted: list[int] = []
    stop = threading.Event()

    def accept() -> None:
        while not stop.is_set():
            try:
                listener.accept()
                accepted.append(1)
            except (TimeoutError, OSError):
                pass

    t = threading.Thread(target=accept, daemon=True)
    t.start()
    code = f"""
import socket, json, os
def tcp(host, port):
    s = socket.socket(); s.settimeout(2)
    try:
        s.connect((host, port)); return True
    except OSError:
        return False
    finally:
        s.close()
try:
    socket.getaddrinfo("example.com", 80); dns = True
except OSError:
    dns = False
print(json.dumps({{
    "loopback_host_port": tcp("127.0.0.1", {port}),
    "bridge_gateway": tcp("172.17.0.1", {port}),
    "internet": tcp("1.1.1.1", 53),
    "metadata": tcp("169.254.169.254", 80),
    "dns": dns,
    "interfaces": sorted(os.listdir("/sys/class/net")),
}}))
"""
    try:
        out = probe(runner, code)
    finally:
        stop.set()
        t.join(timeout=2)
        listener.close()
    assert out["interfaces"] == ["lo"]
    assert not any(
        out[k] for k in ("loopback_host_port", "bridge_gateway", "internet", "metadata", "dns")
    )
    assert accepted == []  # the host listener never saw a connection


def test_no_docker_socket_host_paths_or_foreign_mounts(
    runner: DockerRunner, tmp_path: Path
) -> None:
    (tmp_path / "host-marker.txt").write_text("x")
    code = """
import os, json
mounts = open('/proc/self/mountinfo').read()
print(json.dumps({
  "socket": [p for p in ('/var/run/docker.sock','/run/docker.sock','/docker.sock') if os.path.exists(p)],
  "home": os.listdir('/home') if os.path.exists('/home') else [], "root_listing": sorted(os.listdir('/')),
  "mount_mentions_socket": 'docker.sock' in mounts,
  "mounts": sorted({l.split()[4] for l in mounts.splitlines()}),
}))
"""
    out = probe(runner, code)
    assert out["socket"] == [] and not out["mount_mentions_socket"]
    assert out["home"] == []  # the base image's /home is empty: no host home directory
    assert str(tmp_path) not in json.dumps(out)
    assert {"/workspace", "/tmp"} <= set(out["mounts"])
    assert not any(m.startswith(("/host", "/mnt", "/media", "/Users")) for m in out["mounts"])


def test_filesystem_is_read_only_except_small_noexec_tmpfs(runner: DockerRunner) -> None:
    code = """
import os, json, subprocess, stat
def can_write(path):
    try:
        with open(path, 'w') as f: f.write('x')
        return True
    except OSError:
        return False
script = '/workspace/run.sh'
open(script, 'w').write('#!/bin/sh\\necho hi\\n'); os.chmod(script, 0o755)
try:
    subprocess.run([script], check=True, capture_output=True); exec_ok = True
except (OSError, subprocess.CalledProcessError):
    exec_ok = False
print(json.dumps({"etc": can_write('/etc/sentinel-x'), "usr": can_write('/usr/sentinel-x'),
  "opt": can_write('/opt/sentinel/entry.py'), "root": can_write('/sentinel-x'),
  "workspace": can_write('/workspace/ok'), "tmp": can_write('/tmp/ok'), "exec_from_tmpfs": exec_ok}))
"""
    out = probe(runner, code)
    assert out == {"etc": False, "usr": False, "opt": False, "root": False, "workspace": True, "tmp": True, "exec_from_tmpfs": False}  # fmt: skip


def test_runs_as_unprivileged_user_with_no_capabilities(runner: DockerRunner) -> None:
    code = """
import os, json
st = dict(l.split(':\\t',1) for l in open('/proc/self/status').read().splitlines() if ':\\t' in l)
def can(op):
    try: op(); return True
    except OSError: return False
print(json.dumps({"uid": os.getuid(), "gid": os.getgid(), "euid": os.geteuid(),
  "cap_eff": st['CapEff'].strip(), "cap_bnd": st['CapBnd'].strip(), "no_new_privs": st['NoNewPrivs'].strip(),
  "seccomp": st['Seccomp'].strip(),
  "chown": can(lambda: os.chown('/workspace', 0, 0)),
  "mknod": can(lambda: os.mknod('/workspace/dev', 0o600 | 0o020000, os.makedev(1, 3))),
  "setuid0": can(lambda: os.setuid(0))}))
"""
    out = probe(runner, code)
    assert (out["uid"], out["gid"], out["euid"]) == (65534, 65534, 65534)
    assert int(out["cap_eff"], 16) == 0 and int(out["cap_bnd"], 16) == 0
    assert out["no_new_privs"] == "1" and out["seccomp"] == "2"
    assert not (out["chown"] or out["mknod"] or out["setuid0"])


def test_container_configuration_as_the_daemon_sees_it(runner: DockerRunner) -> None:
    res = go(runner, "print(1)", cpus=0.5, memory_mb=96, pids=40)
    hc = res.host_config
    assert (
        hc["NetworkMode"] == "none" and hc["ReadonlyRootfs"] is True and hc["Privileged"] is False
    )
    assert (
        hc["CapDrop"] == ["ALL"] and not hc["CapAdd"] and "no-new-privileges" in hc["SecurityOpt"]
    )
    assert hc["Memory"] == hc["MemorySwap"] == 96 * 1024 * 1024  # no swap
    assert hc["NanoCpus"] == 500_000_000 and hc["PidsLimit"] == 40
    assert not hc["Binds"] and not hc["Devices"] and hc["IpcMode"] == "none"
    assert res.image_id and res.exit_code == 0


def test_two_sandboxes_never_share_a_workspace(runner: DockerRunner) -> None:
    first = probe(runner, "import json;open('/workspace/secret.txt','w').write('A');open('/tmp/t','w').write('A');print(json.dumps({'wrote':True}))")  # fmt: skip
    second = probe(runner, "import os,json;print(json.dumps({'ws':os.listdir('/workspace'),'tmp':os.listdir('/tmp')}))")  # fmt: skip
    assert first["wrote"] and second == {"ws": [], "tmp": []}


# ---- resource limits -----------------------------------------------------------------------


def test_memory_limit_kills_and_is_reported(runner: DockerRunner) -> None:
    res = go(runner, "b = bytearray(400*1024*1024)\nfor i in range(0, len(b), 4096): b[i] = 1\nprint('survived')", memory_mb=128)  # fmt: skip
    assert res.oom_killed and res.exit_code not in (0, None) and b"survived" not in res.stdout


def test_process_limit_stops_a_fork_bomb(runner: DockerRunner) -> None:
    code = """
import subprocess, json
procs, err = [], None
try:
    for _ in range(400): procs.append(subprocess.Popen(["sleep", "30"]))
except OSError as e:
    err = type(e).__name__
n = len(procs)
for p in procs: p.kill()
print(json.dumps({"spawned": n, "err": err}))
"""
    out = probe(runner, code, pids=32)
    assert out["err"] is not None and out["spawned"] < 32


def test_disk_limits_tmpfs_size_and_single_file_size(runner: DockerRunner) -> None:
    fill = """
import json, errno
n, err = 0, None
try:
    for i in range(20):
        with open(f'/workspace/f{i}', 'wb') as f: f.write(b'x' * (4*1024*1024))
        n += 1
except OSError as e:
    err = e.errno
print(json.dumps({"files": n, "errno": err}))
"""
    out = probe(runner, fill, workspace_mb=32, max_file_mb=8)
    assert out["errno"] == 28 and out["files"] <= 8  # ENOSPC: the tmpfs is full at 32 MiB
    big = "import json\ntry:\n    open('/tmp/big','wb').write(b'x'*(20*1024*1024)); e=None\nexcept OSError as x:\n    e=x.errno\nprint(json.dumps({'errno': e}))"  # fmt: skip
    assert probe(runner, big, tmp_mb=8, max_file_mb=4)["errno"] in (27, 28)  # EFBIG / ENOSPC


def test_output_flood_is_capped_and_does_not_hang(runner: DockerRunner) -> None:
    res = go(runner, "import sys\nfor _ in range(200):\n    sys.stdout.write('A'*50000+'\\n')\nsys.stderr.write('B'*400000)", output_cap_bytes=65536)  # fmt: skip
    assert res.exit_code == 0 and len(res.stdout) == 65536 and len(res.stderr) == 65536
    assert res.stdout_truncated and res.stderr_truncated


# ---- time, cancellation, cleanup ----------------------------------------------------------


def test_timeout_terminates_the_sandbox(runner: DockerRunner) -> None:
    started = time.monotonic()
    res = go(runner, "import time; time.sleep(60)", timeout_seconds=2)
    assert res.timed_out and res.exit_code == 124 and not res.cancelled
    assert time.monotonic() - started < 15


def test_killing_the_in_container_runner_ends_the_container(runner: DockerRunner) -> None:
    started = time.monotonic()
    res = go(
        runner, "import os, time\nos.kill(os.getppid(), 9)\ntime.sleep(60)", timeout_seconds=30
    )
    assert res.exit_code not in (0, None) and not res.cancelled and time.monotonic() - started < 15


def test_host_deadline_still_kills_if_the_in_container_timeout_is_frozen(
    runner: DockerRunner,
) -> None:
    # The command freezes the in-container runner (same uid), so its own timeout never fires.
    code = "import os, signal, time\nos.kill(os.getppid(), signal.SIGSTOP)\ntime.sleep(60)"
    started = time.monotonic()
    res = go(runner, code, timeout_seconds=2)
    assert res.timed_out and not res.cancelled and time.monotonic() - started < 25


def test_cancel_terminates_a_running_sandbox_quickly(runner: DockerRunner) -> None:
    begin = time.monotonic()
    res = go(runner, "import time; time.sleep(60)", stop=lambda: time.monotonic() - begin > 1.5)
    assert res.cancelled and not res.timed_out and time.monotonic() - begin < 15


@pytest.mark.parametrize(
    "code, expect",
    [
        ("print('ok')", {"exit": 0}),
        ("import sys; sys.exit(3)", {"exit": 3}),
        ("raise SystemExit('boom')", {"exit": 1}),
        ("b = bytearray(300*1024*1024)\nfor i in range(0, len(b), 4096): b[i] = 1", {"oom": True}),
    ],
)
def test_container_is_removed_after_success_failure_and_oom(runner: DockerRunner, code: str, expect: dict) -> None:  # fmt: skip
    res = go(runner, code, memory_mb=128)
    assert res.removed and runner._ids() == []
    if "exit" in expect:
        assert res.exit_code == expect["exit"]
    if expect.get("oom"):
        assert res.oom_killed


def test_a_container_that_cannot_start_is_reported_and_leaves_nothing(runner: DockerRunner) -> None:
    bad = SandboxSpec(image="sentinel-no-such-image:none", scope=runner.scope, run_id=uuid.uuid4(), batch_id=uuid.uuid4(), command=("python",), limits=lim(), extract_source=False)  # fmt: skip
    res = runner.run(bad, None, lambda: False)
    assert res.start_error and not res.started and res.removed and runner._ids() == []


def test_cleanup_by_batch_removes_a_running_orphan_and_verifies_it(runner: DockerRunner) -> None:
    batch = uuid.uuid4()
    spec = spec_for(runner, ("python", "-I", "-c", "import time; time.sleep(60)"), batch=batch)
    holder: list[SandboxResult] = []
    t = threading.Thread(target=lambda: holder.append(runner.run(spec, None, lambda: False)))
    t.start()
    deadline = time.time() + 20
    while time.time() < deadline and not runner._ids(f"sentinel.sandbox.batch={batch}"):
        time.sleep(0.2)
    assert runner._ids(f"sentinel.sandbox.batch={batch}"), "sandbox never appeared"
    assert runner.cleanup_batch(uuid.uuid4()) is True  # another batch: nothing to remove...
    assert runner._ids(f"sentinel.sandbox.batch={batch}")  # ...and ours is untouched
    begin = time.time()
    assert runner.cleanup_batch(batch) is True
    t.join(timeout=20)
    assert not t.is_alive() and time.time() - begin < 20 and runner._ids() == []


def test_janitor_sweeps_only_old_containers_of_its_own_scope(runner: DockerRunner) -> None:
    mine = spec_for(runner, ("python", "-I", "-c", "print(1)"))
    other_scope = DockerRunner(f"other-{uuid.uuid4().hex[:8]}")
    theirs = spec_for(other_scope, ("python", "-I", "-c", "print(1)"))
    foreign = f"sentinel-sbx-foreign-{uuid.uuid4().hex[:8]}"
    plain = f"sentinel-plain-{uuid.uuid4().hex[:8]}"
    try:
        for r, s, name in ((runner, mine, "sentinel-sbx-a" + uuid.uuid4().hex[:8]), (other_scope, theirs, "sentinel-sbx-b" + uuid.uuid4().hex[:8])):  # fmt: skip
            assert r._docker(*create_argv(r.docker_bin, name, s)[1:])[0] == 0
        # A look-alike without the sandbox labels must never be touched.
        assert runner._docker("create", "--name", plain, "--label", f"sentinel.sandbox.scope={runner.scope}", IMAGE)[0] == 0  # fmt: skip
        assert runner.sweep(3600) == 0  # nothing is old yet
        time.sleep(1.1)
        assert runner.sweep(1) == 1  # only our scope's labelled container
        assert runner._ids() == []
        assert len(other_scope._ids() or []) == 1  # the other scope survived
        assert (
            runner._docker("inspect", "--format", "{{.Id}}", plain)[0] == 0
        )  # unlabelled survived
    finally:
        for left in other_scope._ids() or []:
            other_scope._docker("rm", "-f", "-v", left)
        runner._docker("rm", "-f", "-v", plain, foreign)


# ---- archives inside the sandbox -----------------------------------------------------------


def run_archive(r: DockerRunner, data: bytes, **limits: int | float) -> SandboxResult:
    command = ("python", "-I", "/opt/sentinel/smoke.py")
    res = r.run(spec_for(r, command, extract=True, **limits), data, lambda: False)
    assert res.removed and r._ids() == []
    return res


def _hostile(kind: str) -> bytes:
    import io
    import stat
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        if kind == "traversal":
            zf.writestr("../../tmp/evil", "x")
        elif kind == "absolute":
            zf.writestr("/workspace/evil", "x")
        elif kind == "symlink":
            info = zipfile.ZipInfo("link")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "/etc/passwd")
        elif kind == "device":
            info = zipfile.ZipInfo("dev")
            info.external_attr = (stat.S_IFCHR | 0o666) << 16
            zf.writestr(info, "")
        elif kind == "bomb":
            zf.writestr("zeros.bin", b"\0" * 40_000_000, zipfile.ZIP_DEFLATED)
        elif kind == "many":
            for i in range(600):
                zf.writestr(f"f{i}", "x")
    return buf.getvalue()


@pytest.mark.parametrize("kind", ["traversal", "absolute", "symlink", "device", "bomb", "many"])
def test_hostile_archives_are_rejected_inside_the_sandbox(runner: DockerRunner, kind: str) -> None:
    res = run_archive(runner, _hostile(kind), max_extract_mb=16, max_file_mb=8, max_files=500)
    assert res.exit_code == 70 and b"archive rejected" in res.stderr
    assert res.stdout == b""  # the command never ran


def test_garbage_and_oversized_input_are_rejected(runner: DockerRunner) -> None:
    assert run_archive(runner, b"definitely not a zip").exit_code == 70
    assert (
        run_archive(runner, make_zip({"big": os.urandom(5000)}), max_zip_bytes=1000).exit_code == 70
    )
    assert run_archive(runner, b"").exit_code == 70


def test_valid_archive_is_unpacked_and_described_without_running_project_code(runner: DockerRunner) -> None:  # fmt: skip
    data = make_zip({
        "app/main.py": "print('EXECUTED-BY-PROJECT-CODE')", "conftest.py": "raise SystemExit('EXECUTED')",
        "sitecustomize.py": "print('EXECUTED-BY-PROJECT-CODE')", "setup.py": "print('EXECUTED-BY-PROJECT-CODE')",
        "README.md": "hello", "pkg/__init__.py": "",
    })  # fmt: skip
    res = run_archive(runner, data)
    assert res.exit_code == 0 and b"EXECUTED" not in res.stdout + res.stderr
    census = json.loads(res.stdout)
    assert (
        census["files"] == 6 and census["uid"] == 65534 and census["project_code_executed"] is False
    )
