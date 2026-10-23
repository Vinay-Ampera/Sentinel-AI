"""Runs one sandbox container through the Docker CLI (Stage 8).

Only fixed argument vectors are executed (no shell), with a minimal environment: none of the
worker's own secrets are passed to the CLI. The container is created, fed its source archive
on stdin (no host path is ever mounted), started attached with output read through a size
cap, supervised for cancel/timeout, inspected for its real exit state, and always removed.
Containers carry labels so a lost worker's leftovers can be found and removed by batch or by
age (``cleanup_batch`` / ``sweep``), and the in-container runner enforces its own timeout.
"""

import json
import logging
import os
import shutil
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sentinel_ai.execution.sandbox_spec import (
    LABEL_BATCH,
    LABEL_SANDBOX,
    LABEL_SCOPE,
    SandboxSpec,
    create_argv,
)

logger = logging.getLogger(__name__)

RESULT_TAIL_BYTES = 3 * 1024 * 1024  # base64 of the largest framed result file, with margin
POLL_SECONDS = 0.5
HOST_GRACE_SECONDS = 5  # the host kills a little after the in-container timeout fires
COMMAND_TIMEOUT = 30
EXIT_TIMEOUT = 124
_KEEP_ENV = ("PATH", "HOME", "DOCKER_HOST", "DOCKER_CONFIG", "DOCKER_CONTEXT", "XDG_RUNTIME_DIR")


@dataclass
class SandboxResult:
    started: bool = False
    start_error: str | None = None
    exit_code: int | None = None
    oom_killed: bool = False
    timed_out: bool = False
    cancelled: bool = False
    stdout: bytes = b""
    stderr: bytes = b""
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    stdout_tail: bytes = b""  # the last bytes of stdout, where the result frame is written
    duration_ms: int = 0
    image_id: str | None = None
    host_config: dict[str, Any] = field(default_factory=dict)
    removed: bool = False


class _BoundedReader(threading.Thread):
    """Reads a pipe to the end, keeping at most ``cap`` bytes (the rest is discarded so the
    container never blocks on a full pipe)."""

    def __init__(self, stream: Any, cap: int, tail_cap: int = 0) -> None:
        super().__init__(daemon=True)
        self._stream = stream
        self._cap = cap
        self._tail_cap = tail_cap
        self.data = bytearray()
        self.tail = bytearray()
        self.truncated = False

    def run(self) -> None:
        try:
            while chunk := self._stream.read(65536):
                room = self._cap - len(self.data)
                if room > 0:
                    self.data += chunk[:room]
                if len(chunk) > room:
                    self.truncated = True
                if self._tail_cap:
                    self.tail += chunk
                    if len(self.tail) > self._tail_cap:
                        del self.tail[: len(self.tail) - self._tail_cap]
        except (OSError, ValueError):
            pass


class DockerRunner:
    def __init__(self, scope: str, docker_bin: str | None = None) -> None:
        self.scope = scope
        self.docker_bin = docker_bin or shutil.which("docker") or "docker"
        self._env = {k: os.environ[k] for k in _KEEP_ENV if k in os.environ}

    # ---- low-level -------------------------------------------------------------------------

    def _docker(self, *args: str, timeout: float = COMMAND_TIMEOUT) -> tuple[int, str]:
        try:
            proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
                [self.docker_bin, *args], capture_output=True, timeout=timeout,
                env=self._env, stdin=subprocess.DEVNULL, check=False,
            )  # fmt: skip
        except (OSError, subprocess.SubprocessError) as exc:
            return -1, type(exc).__name__
        return proc.returncode, proc.stdout.decode("utf-8", errors="replace").strip()

    def available(self) -> bool:
        return self._docker("version", "--format", "{{.Server.Version}}", timeout=10)[0] == 0

    def image_exists(self, image: str) -> bool:
        return self._docker("image", "inspect", "--format", "{{.Id}}", image, timeout=10)[0] == 0

    def image_label(self, image: str, label: str) -> str | None:
        """A label of a local image (set at build time, so it is the operator's word and not
        something the container can say about itself)."""
        code, out = self._docker("image", "inspect", "--format", "{{json .Config.Labels}}", image, timeout=10)  # fmt: skip
        if code != 0:
            return None
        try:
            labels = json.loads(out)
        except ValueError:
            return None
        value = labels.get(label) if isinstance(labels, dict) else None
        return value if isinstance(value, str) else None

    def _inspect(self, name: str) -> dict[str, Any]:
        code, out = self._docker("inspect", name)
        if code != 0:
            return {}
        try:
            data = json.loads(out)
            return dict(data[0])
        except (ValueError, IndexError, TypeError):
            return {}

    # ---- one run ---------------------------------------------------------------------------

    def run(
        self,
        spec: SandboxSpec,
        stdin_data: bytes | None,
        should_stop: Callable[[], bool],
    ) -> SandboxResult:
        name = f"sentinel-sbx-{uuid.uuid4().hex}"
        result = SandboxResult()
        started_at = time.monotonic()
        try:
            code, out = self._docker(*create_argv(self.docker_bin, name, spec)[1:])
            if code != 0:
                result.start_error = "the sandbox container could not be created"
                logger.warning("sandbox create failed (docker exit %s)", code)
                return result
            self._supervise(name, spec, stdin_data, should_stop, result)
        finally:
            result.duration_ms = int((time.monotonic() - started_at) * 1000)
            self._docker("rm", "-f", "-v", name)
            result.removed = self._docker("inspect", "--format", "{{.Id}}", name)[0] != 0
        return result

    def _supervise(
        self,
        name: str,
        spec: SandboxSpec,
        stdin_data: bytes | None,
        should_stop: Callable[[], bool],
        result: SandboxResult,
    ) -> None:
        cap = spec.limits.output_cap_bytes
        try:
            proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
                [self.docker_bin, "start", "-a", "-i", name], env=self._env,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )  # fmt: skip
        except OSError:
            result.start_error = "the sandbox container could not be started"
            return
        tail_cap = RESULT_TAIL_BYTES if spec.result_file else 0
        out_reader = _BoundedReader(proc.stdout, cap, tail_cap)
        err_reader = _BoundedReader(proc.stderr, cap)
        out_reader.start()
        err_reader.start()

        def feed() -> None:
            try:
                if stdin_data:
                    proc.stdin.write(stdin_data)  # type: ignore[union-attr]
                proc.stdin.close()  # type: ignore[union-attr]
            except (BrokenPipeError, OSError, ValueError):
                pass

        feeder = threading.Thread(target=feed, daemon=True)
        feeder.start()
        result.started = True

        deadline = time.monotonic() + spec.limits.timeout_seconds + HOST_GRACE_SECONDS
        while True:
            try:
                proc.wait(timeout=POLL_SECONDS)
                break
            except subprocess.TimeoutExpired:
                pass
            if should_stop():
                result.cancelled = True
            elif time.monotonic() > deadline:
                result.timed_out = True
            else:
                continue
            self._docker("kill", name)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            break

        feeder.join(timeout=5)
        out_reader.join(timeout=5)
        err_reader.join(timeout=5)
        result.stdout, result.stderr = bytes(out_reader.data), bytes(err_reader.data)
        result.stdout_tail = bytes(out_reader.tail)
        result.stdout_truncated, result.stderr_truncated = (
            out_reader.truncated,
            err_reader.truncated,
        )

        info = self._inspect(name)
        state = info.get("State", {})
        host = info.get("HostConfig", {})
        result.exit_code = state.get("ExitCode") if isinstance(state.get("ExitCode"), int) else None
        result.oom_killed = bool(state.get("OOMKilled"))
        result.image_id = info.get("Image")
        result.host_config = {
            k: host.get(k)
            for k in (
                "NetworkMode", "ReadonlyRootfs", "Privileged", "CapDrop", "CapAdd", "SecurityOpt",
                "Memory", "MemorySwap", "NanoCpus", "PidsLimit", "Binds", "Devices", "Runtime",
                "IpcMode", "PidMode", "Tmpfs", "Ulimits",
            )
        }  # fmt: skip
        if result.exit_code == EXIT_TIMEOUT:
            result.timed_out = True

    # ---- cleanup by label --------------------------------------------------------------------

    def _ids(self, *extra_labels: str) -> list[str] | None:
        args = ["ps", "-a", "-q", "--no-trunc", "--filter", f"label={LABEL_SANDBOX}=1",
                "--filter", f"label={LABEL_SCOPE}={self.scope}"]  # fmt: skip
        for label in extra_labels:
            args += ["--filter", f"label={label}"]
        code, out = self._docker(*args)
        return out.split() if code == 0 else None

    def cleanup_batch(self, batch_id: uuid.UUID) -> bool:
        """Kill and remove every container of the batch; True only if none remain (verified)."""
        label = f"{LABEL_BATCH}={batch_id}"
        ids = self._ids(label)
        if ids is None:
            return False
        if ids:
            self._docker("rm", "-f", "-v", *ids)
        return self._ids(label) == []

    def sweep(self, max_age_seconds: float) -> int:
        """Remove this scope's sandbox containers older than ``max_age_seconds`` (leaked by a
        crashed worker). Never touches containers without both sandbox labels."""
        ids = self._ids()
        if not ids:
            return 0
        code, out = self._docker("inspect", "--format", "{{.Id}} {{.Created}}", *ids)
        if code != 0:
            return 0
        now = datetime.now(UTC)
        stale = []
        for line in out.splitlines():
            cid, _, created = line.partition(" ")
            try:
                when = datetime.fromisoformat(created.split(".")[0] + "+00:00")
            except ValueError:
                continue
            if (now - when).total_seconds() > max_age_seconds:
                stale.append(cid)
        if stale:
            self._docker("rm", "-f", "-v", *stale)
        return len(stale)
