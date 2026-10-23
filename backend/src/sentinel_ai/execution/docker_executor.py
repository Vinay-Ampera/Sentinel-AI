"""Sandboxed executor (Stage 8): the Stage 7 ``Executor`` backed by disposable containers.

For each planned test it looks up a fixed command by catalog check id, re-verifies the source
archive (project ownership was checked by the worker; here the hash and the archive headers),
sends it to a locked-down container over stdin, and turns the container's real exit state into
a result plus evidence. Network is always disabled. Checks without a runner yet are recorded
as skipped, and checks that need a network target are blocked, before anything starts.
"""

import io
import logging
import uuid
from collections.abc import Callable
from pathlib import Path

from sentinel_ai.core.config import Settings
from sentinel_ai.execution import commands, evidence
from sentinel_ai.execution.docker_runner import DockerRunner, SandboxResult
from sentinel_ai.execution.interface import EvidenceItem, ExecutionOutcome, ExecutionRequest
from sentinel_ai.execution.sandbox_spec import SandboxLimits, SandboxSpec
from sentinel_ai.services.archive import (
    ArchiveLimits,
    ArchiveRejected,
    inspect_archive,
    open_archive,
)
from sentinel_ai.services.artifact_store import ArtifactStore, sha256_bytes

logger = logging.getLogger(__name__)

EXIT_REJECTED = 70  # the in-container runner refused the archive


class DockerSandboxExecutor:
    def __init__(self, settings: Settings, runner: DockerRunner | None = None) -> None:
        self._settings = settings
        self._runner = runner or DockerRunner(settings.sandbox_scope, settings.sandbox_docker_bin)
        self._store = ArtifactStore(settings.artifact_root())
        self._secrets = evidence.secret_values(settings)

    # ---- Executor protocol -------------------------------------------------------------------

    def execute(
        self, request: ExecutionRequest, should_stop: Callable[[], bool]
    ) -> ExecutionOutcome:
        command = commands.lookup(request.check_id)
        if command is None:
            return ExecutionOutcome(
                "skipped", "Not executed: no sandbox runner exists for this check yet."
            )
        if command.needs_network:
            return ExecutionOutcome(
                "blocked", "Blocked: the sandbox has no network access, which this check needs."
            )
        archive: bytes | None = None
        if command.needs_workspace:
            loaded = self._load_archive(request)
            if isinstance(loaded, ExecutionOutcome):
                return loaded
            archive = loaded
        if should_stop():
            return ExecutionOutcome("cancelled", "Stopped before the sandbox started.")

        spec = self._spec(request, command, extract=archive is not None)
        result = self._runner.run(spec, archive, should_stop)
        return self._outcome(request, spec, result)

    def terminate(self, batch_id: uuid.UUID) -> bool:
        return self._runner.cleanup_batch(batch_id)

    def sweep(self) -> int:
        s = self._settings
        return self._runner.sweep(s.sandbox_test_timeout_seconds + s.job_cancel_grace_seconds + 120)

    # ---- internals ---------------------------------------------------------------------------

    def _limits(self, request: ExecutionRequest) -> SandboxLimits:
        s = self._settings
        return SandboxLimits(
            cpus=s.sandbox_cpus,
            memory_mb=s.sandbox_memory_mb,
            pids=s.sandbox_pids,
            workspace_mb=s.sandbox_workspace_mb,
            tmp_mb=s.sandbox_tmp_mb,
            timeout_seconds=min(request.timeout_seconds, s.sandbox_test_timeout_seconds),
            max_extract_mb=s.sandbox_max_extract_mb,
            max_file_mb=s.sandbox_max_file_mb,
            max_files=s.zip_max_files,
            max_zip_bytes=s.upload_max_mb * 1024 * 1024,
            output_cap_bytes=s.sandbox_output_cap_bytes,
        )

    def _spec(
        self, request: ExecutionRequest, command: commands.CheckCommand, *, extract: bool
    ) -> SandboxSpec:
        s = self._settings
        return SandboxSpec(
            image=s.sandbox_image,
            scope=s.sandbox_scope,
            run_id=request.run_id,
            batch_id=request.batch_id,
            command=command.argv,
            limits=self._limits(request),
            extract_source=extract,
            runtime=s.sandbox_runtime,
        )

    def _load_archive(self, request: ExecutionRequest) -> bytes | ExecutionOutcome:
        ref = request.workspace
        if ref is None:
            return ExecutionOutcome(
                "blocked", "Blocked: the check has no uploaded source archive to run against."
            )
        limit = self._settings.upload_max_mb * 1024 * 1024
        if ref.size_bytes > limit:
            return ExecutionOutcome(
                "blocked", "Blocked: the source archive exceeds the size limit."
            )
        try:
            path = self._store.path_for(ref.storage_key)
            if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
                raise OSError("unusable archive file")
            data = Path(path).read_bytes()
        except (ValueError, OSError):
            return ExecutionOutcome("blocked", "Blocked: the source archive could not be read.")
        if sha256_bytes(data) != ref.sha256:  # integrity: read once, check, send those bytes
            return ExecutionOutcome(
                "blocked", "Blocked: the source archive does not match its recorded hash."
            )
        try:
            with open_archive(io.BytesIO(data)) as zf:
                inspect_archive(
                    zf,
                    ArchiveLimits(
                        max_upload_bytes=limit,
                        max_uncompressed_bytes=self._settings.sandbox_max_extract_mb * 1024 * 1024,
                        max_files=self._settings.zip_max_files,
                    ),
                )
        except ArchiveRejected as exc:
            return ExecutionOutcome(
                "blocked", f"Blocked: the source archive was rejected ({exc.code})."
            )
        return data

    def _outcome(
        self, request: ExecutionRequest, spec: SandboxSpec, r: SandboxResult
    ) -> ExecutionOutcome:
        items = self._evidence(request, spec, r)
        if r.start_error:
            return ExecutionOutcome("failed_to_start", r.start_error, evidence=items)
        if r.cancelled:
            return ExecutionOutcome("cancelled", "Stopped: the sandbox was terminated.", duration_ms=r.duration_ms, evidence=items)  # fmt: skip
        if r.timed_out:
            return ExecutionOutcome("timed_out", "The sandbox exceeded its time limit and was terminated.", exit_code=r.exit_code, duration_ms=r.duration_ms, evidence=items)  # fmt: skip
        if r.oom_killed:
            return ExecutionOutcome("error", "The sandbox exceeded its memory limit and was terminated.", exit_code=r.exit_code, duration_ms=r.duration_ms, evidence=items)  # fmt: skip
        if r.exit_code == EXIT_REJECTED:
            return ExecutionOutcome("error", "The sandbox refused the source archive; see the log.", exit_code=r.exit_code, duration_ms=r.duration_ms, evidence=items)  # fmt: skip
        if r.exit_code == 0:
            return ExecutionOutcome("passed", "The sandbox command finished with exit code 0.", exit_code=0, duration_ms=r.duration_ms, evidence=items)  # fmt: skip
        return ExecutionOutcome("failed", f"The sandbox command exited with code {r.exit_code}.", exit_code=r.exit_code, duration_ms=r.duration_ms, evidence=items)  # fmt: skip

    def _evidence(self, request: ExecutionRequest, spec: SandboxSpec, r: SandboxResult) -> tuple[EvidenceItem, ...]:  # fmt: skip
        s = self._settings
        cap = s.sandbox_output_cap_bytes
        lim = spec.limits
        manifest = {
            "schema": 1,
            "check_id": request.check_id,
            "attempt": request.attempt,
            "image": spec.image,
            "image_id": r.image_id,
            "network": "none",
            "limits": {
                "cpus": lim.cpus,
                "memory_mb": lim.memory_mb,
                "pids": lim.pids,
                "workspace_mb": lim.workspace_mb,
                "tmp_mb": lim.tmp_mb,
                "timeout_seconds": lim.timeout_seconds,
                "max_extract_mb": lim.max_extract_mb,
                "max_file_mb": lim.max_file_mb,
                "output_cap_bytes": lim.output_cap_bytes,
            },  # fmt: skip
            "container": r.host_config,
            "exit_code": r.exit_code,
            "oom_killed": r.oom_killed,
            "timed_out": r.timed_out,
            "cancelled": r.cancelled,
            "started": r.started,
            "stdout_truncated": r.stdout_truncated,
            "stderr_truncated": r.stderr_truncated,
            "duration_ms": r.duration_ms,
            "container_removed": r.removed,
        }
        return (
            evidence.log_item("stdout.log", r.stdout, self._secrets, cap, r.stdout_truncated),
            evidence.log_item("stderr.log", r.stderr, self._secrets, cap, r.stderr_truncated),
            evidence.manifest_item(manifest),
        )
