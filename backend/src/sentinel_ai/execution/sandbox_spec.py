"""What a sandbox container looks like (Stage 8). Pure functions, no Docker calls.

The argument vector is built only from validated values: ids come from UUIDs, numbers from
bounded settings, and the command from the server's fixed table. There is deliberately no
shell, no bind mount, no volume, no device, no environment pass-through, no Docker socket
and no network. Tests assert these properties on the generated vector.
"""

import ipaddress
import re
import uuid
from dataclasses import dataclass

LABEL_SANDBOX = "sentinel.sandbox"
LABEL_SCOPE = "sentinel.sandbox.scope"
LABEL_RUN = "sentinel.sandbox.run"
LABEL_BATCH = "sentinel.sandbox.batch"
RUNNER_UID = "65534:65534"
RESULT_MAX_BYTES = 2 * 1024 * 1024  # largest result file the in-image runner will frame
_NONCE = re.compile(r"[0-9a-f]{16,64}")
_RESULT_PATH = re.compile(r"/(?:tmp|workspace)/[A-Za-z0-9_.-]{1,64}")

_IMAGE = re.compile(r"[a-z0-9][a-z0-9_./:@-]{0,199}")
_PLAIN = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}")


@dataclass(frozen=True)
class SandboxLimits:
    cpus: float
    memory_mb: int
    pids: int
    workspace_mb: int
    tmp_mb: int
    timeout_seconds: int
    max_extract_mb: int
    max_file_mb: int
    max_files: int
    max_zip_bytes: int
    output_cap_bytes: int


_HOST = re.compile(
    r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?){1,10}"
)
BLACKHOLE_DNS = "192.0.2.1"  # TEST-NET-1 (RFC 5737): nothing answers, so only pinned names resolve


@dataclass(frozen=True)
class EgressSpec:
    """The one exception to ``--network none`` (Stage 10, ZAP against an authorized target).

    ``network`` is a Docker network the operator provisioned and attested to have host-firewall
    egress rules allowing only the scan targets (see SANDBOX_THREAT_MODEL.md). The target host
    is pinned to the address the worker resolved and verified as public, and DNS points at a
    black hole, so the container can resolve no other name.
    """

    network: str
    host: str
    ip: str

    def validate(self) -> None:
        if not _PLAIN.fullmatch(self.network) or self.network in ("host", "bridge", "none"):
            raise ValueError("invalid egress network")
        if not _HOST.fullmatch(self.host):
            raise ValueError("invalid egress host")
        try:
            ip = ipaddress.ip_address(self.ip)
        except ValueError:
            raise ValueError("invalid egress address") from None
        if not ip.is_global or ip.is_multicast:
            raise ValueError("egress address must be public")


@dataclass(frozen=True)
class SandboxSpec:
    image: str
    scope: str
    run_id: uuid.UUID
    batch_id: uuid.UUID
    command: tuple[str, ...]
    limits: SandboxLimits
    extract_source: bool
    runtime: str | None = None
    result_file: str | None = None  # file under /tmp the runner frames onto stdout at the end
    result_nonce: str | None = None
    egress: EgressSpec | None = None

    def validate(self) -> None:
        if not _IMAGE.fullmatch(self.image):
            raise ValueError("invalid image reference")
        if not _PLAIN.fullmatch(self.scope):
            raise ValueError("invalid scope label")
        if self.runtime is not None and not _PLAIN.fullmatch(self.runtime):
            raise ValueError("invalid runtime name")
        if not self.command or any(("\x00" in a or not a) for a in self.command):
            raise ValueError("invalid command")
        if self.egress is not None:
            self.egress.validate()
        if (self.result_file is None) != (self.result_nonce is None):
            raise ValueError("result file and nonce go together")
        if self.result_file is not None and not _RESULT_PATH.fullmatch(self.result_file):
            raise ValueError("invalid result file")
        if self.result_nonce is not None and not _NONCE.fullmatch(self.result_nonce):
            raise ValueError("invalid result nonce")
        lim = self.limits
        positive = (
            lim.cpus,
            lim.memory_mb,
            lim.pids,
            lim.workspace_mb,
            lim.tmp_mb,
            lim.timeout_seconds,
        )
        if any(v <= 0 for v in positive):
            raise ValueError("limits must be positive")
        if lim.workspace_mb + lim.tmp_mb >= lim.memory_mb:
            raise ValueError("tmpfs sizes count against memory")


def labels(spec: SandboxSpec) -> dict[str, str]:
    return {
        LABEL_SANDBOX: "1",
        LABEL_SCOPE: spec.scope,
        LABEL_RUN: str(spec.run_id),
        LABEL_BATCH: str(spec.batch_id),
    }


def _network_args(egress: EgressSpec | None) -> list[str]:
    if egress is None:
        return ["--network", "none"]
    return [
        "--network", egress.network,
        "--add-host", f"{egress.host}:{egress.ip}",
        "--dns", BLACKHOLE_DNS,
    ]  # fmt: skip


def create_argv(docker_bin: str, name: str, spec: SandboxSpec) -> list[str]:
    """`docker create ...` for one disposable, locked-down container."""
    spec.validate()
    lim = spec.limits
    mem = f"{lim.memory_mb}m"
    tmpfs = "rw,nosuid,nodev,noexec,size={size}m,uid=65534,gid=65534,mode=0700"
    argv = [
        docker_bin, "create", "--name", name,
        *[a for k, v in labels(spec).items() for a in ("--label", f"{k}={v}")],
        *_network_args(spec.egress),
        "--read-only",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--user", RUNNER_UID,
        "--pids-limit", str(lim.pids),
        "--memory", mem, "--memory-swap", mem,
        "--cpus", f"{lim.cpus:g}",
        "--ulimit", "nofile=256:256",
        "--ulimit", "core=0",
        "--ulimit", f"fsize={lim.max_file_mb * 1024 * 1024}:{lim.max_file_mb * 1024 * 1024}",
        "--tmpfs", f"/workspace:{tmpfs.format(size=lim.workspace_mb)}",
        "--tmpfs", f"/tmp:{tmpfs.format(size=lim.tmp_mb)}",
        "--init", "--ipc", "none", "--log-driver", "none",
        "--stop-timeout", "2", "--interactive",
    ]  # fmt: skip
    if spec.runtime:
        argv += ["--runtime", spec.runtime]
    argv.append(spec.image)  # entrypoint = the trusted runner; everything below is its argv
    if spec.extract_source:
        argv += [
            "--extract", str(lim.max_zip_bytes), str(lim.max_files),
            str(lim.max_extract_mb * 1024 * 1024), str(lim.max_file_mb * 1024 * 1024),
        ]  # fmt: skip
    if spec.result_file and spec.result_nonce:
        argv += ["--result-file", spec.result_file, spec.result_nonce, str(RESULT_MAX_BYTES)]
    argv += ["--timeout", str(lim.timeout_seconds), "--", *spec.command]
    return argv
