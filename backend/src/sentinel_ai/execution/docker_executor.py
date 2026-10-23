"""Sandboxed executor (Stage 8): the Stage 7 ``Executor`` backed by disposable containers.

For each planned test it looks up a fixed command by catalog check id, re-verifies the source
archive (project ownership was checked by the worker; here the hash and the archive headers),
sends it to a locked-down container over stdin, and turns the container's real exit state into
a result plus evidence. Network is always disabled. Checks without a runner yet are recorded
as skipped, and checks that need a network target are blocked, before anything starts.
"""

import io
import logging
import secrets
import uuid
from collections.abc import Callable
from pathlib import Path

from sentinel_ai.core.config import Settings
from sentinel_ai.execution import commands, evidence, frames, junit
from sentinel_ai.execution.docker_runner import DockerRunner, SandboxResult
from sentinel_ai.execution.interface import (
    CaseResult,
    EvidenceItem,
    ExecutionOutcome,
    ExecutionRequest,
)
from sentinel_ai.execution.sandbox_spec import RESULT_MAX_BYTES, SandboxLimits, SandboxSpec
from sentinel_ai.services.archive import (
    ArchiveLimits,
    ArchiveRejected,
    inspect_archive,
    open_archive,
)
from sentinel_ai.services.artifact_store import ArtifactStore, sha256_bytes

logger = logging.getLogger(__name__)

EXIT_REJECTED = 70  # the in-container runner refused the archive
PYTEST_NO_TESTS = 5


class DockerSandboxExecutor:
    def __init__(self, settings: Settings, runner: DockerRunner | None = None) -> None:
        self._settings = settings
        self._runner = runner or DockerRunner(settings.sandbox_scope, settings.sandbox_docker_bin)
        self._store = ArtifactStore(settings.artifact_root())
        self._secrets = evidence.secret_values(settings)
        if settings.sandbox_allow_project_code and settings.sandbox_runtime is None:
            logger.warning(
                "project code runs under plain Docker (shared kernel): SANDBOX_ACCEPT_SHARED_KERNEL"
            )

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
        if command.runs_project_code and not self._settings.sandbox_allow_project_code:
            return ExecutionOutcome(
                "blocked",
                "Blocked: running a project's own code is not enabled on this deployment.",
            )
        try:
            argv = command.argv_for(request.parameters)
            requested_timeout = commands.timeout_parameter(request.parameters)
        except commands.InvalidParameters as exc:
            return ExecutionOutcome("blocked", f"Blocked: {exc}.")
        archive: bytes | None = None
        if command.needs_workspace:
            loaded = self._load_archive(request)
            if isinstance(loaded, ExecutionOutcome):
                return loaded
            archive = loaded
        if should_stop():
            return ExecutionOutcome("cancelled", "Stopped before the sandbox started.")

        nonce = secrets.token_hex(16) if command.result_file else None
        spec = self._spec(
            request, command, argv, requested_timeout, extract=archive is not None, nonce=nonce
        )
        result = self._runner.run(spec, archive, should_stop)
        return self._outcome(request, spec, result, command, nonce)

    def terminate(self, batch_id: uuid.UUID) -> bool:
        return self._runner.cleanup_batch(batch_id)

    def sweep(self) -> int:
        s = self._settings
        return self._runner.sweep(s.sandbox_test_timeout_seconds + s.job_cancel_grace_seconds + 120)

    # ---- internals ---------------------------------------------------------------------------

    def _limits(self, request: ExecutionRequest, requested: int | None) -> SandboxLimits:
        s = self._settings
        timeout = min(request.timeout_seconds, s.sandbox_test_timeout_seconds, requested or 10**9)
        return SandboxLimits(
            cpus=s.sandbox_cpus,
            memory_mb=s.sandbox_memory_mb,
            pids=s.sandbox_pids,
            workspace_mb=s.sandbox_workspace_mb,
            tmp_mb=s.sandbox_tmp_mb,
            timeout_seconds=timeout,
            max_extract_mb=s.sandbox_max_extract_mb,
            max_file_mb=s.sandbox_max_file_mb,
            max_files=s.zip_max_files,
            max_zip_bytes=s.upload_max_mb * 1024 * 1024,
            output_cap_bytes=s.sandbox_output_cap_bytes,
        )

    def _spec(
        self,
        request: ExecutionRequest,
        command: commands.CheckCommand,
        argv: tuple[str, ...],
        requested_timeout: int | None,
        *,
        extract: bool,
        nonce: str | None,
    ) -> SandboxSpec:
        s = self._settings
        return SandboxSpec(
            image=s.sandbox_image,
            scope=s.sandbox_scope,
            run_id=request.run_id,
            batch_id=request.batch_id,
            command=argv,
            limits=self._limits(request, requested_timeout),
            extract_source=extract,
            runtime=s.sandbox_runtime,
            result_file=command.result_file,
            result_nonce=nonce,
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

    # ---- turning the container's real state into a result -------------------------------------

    def _clean(self, text: str | None) -> str | None:
        if text is None:
            return None
        return evidence.redact(text.encode(), self._secrets).decode()

    def _report(
        self, command: commands.CheckCommand, nonce: str | None, r: SandboxResult
    ) -> tuple[bytes | None, junit.ParsedReport | None, str | None]:
        """(raw result file, parsed cases, problem). Only for runners that produce one."""
        if not command.result_file or nonce is None:
            return None, None, None
        raw = frames.extract(r.stdout_tail or r.stdout, nonce, RESULT_MAX_BYTES)
        if raw is None:
            return None, None, "no result file was produced"
        try:
            return raw, junit.parse(raw), None
        except junit.InvalidReport as exc:
            return None, None, str(exc)

    def _outcome(
        self,
        request: ExecutionRequest,
        spec: SandboxSpec,
        r: SandboxResult,
        command: commands.CheckCommand,
        nonce: str | None,
    ) -> ExecutionOutcome:
        raw, report, problem = self._report(command, nonce, r)
        items = self._evidence(request, spec, r, command, raw, report, problem)
        cases = self._cases(report)
        common = {"exit_code": r.exit_code, "duration_ms": r.duration_ms, "evidence": items, "cases": cases}  # fmt: skip

        def out(status: str, summary: str) -> ExecutionOutcome:
            return ExecutionOutcome(status, summary, **common)  # type: ignore[arg-type]

        if r.start_error:
            return ExecutionOutcome("failed_to_start", r.start_error, evidence=items)
        if r.cancelled:
            return out("cancelled", "Stopped: the sandbox was terminated.")
        if r.timed_out:
            return out("timed_out", "The sandbox exceeded its time limit and was terminated.")
        if r.oom_killed:
            return out("error", "The sandbox exceeded its memory limit and was terminated.")
        if r.exit_code == EXIT_REJECTED:
            return out("error", "The sandbox refused the source archive; see the log.")
        if command.kind == "pytest":
            return self._pytest_outcome(r, report, problem, out)
        if r.exit_code == 0:
            return out("passed", "The sandbox command finished with exit code 0.")
        return out("failed", f"The sandbox command exited with code {r.exit_code}.")

    def _pytest_outcome(
        self,
        r: SandboxResult,
        report: junit.ParsedReport | None,
        problem: str | None,
        out: Callable[[str, str], ExecutionOutcome],
    ) -> ExecutionOutcome:
        counts = report.counts() if report else {}
        listing = ", ".join(
            f"{counts[k]} {k}" for k in ("passed", "failed", "error", "skipped") if counts.get(k)
        )
        base = f"pytest: {listing}." if listing else f"pytest exited with code {r.exit_code}."
        if report is None and problem:
            base += f" ({problem})"
        if report is not None and report.truncated:
            base += f" Only the first {junit.MAX_CASES} cases were kept."
        hint = ""
        text = (r.stdout + r.stderr).decode("utf-8", errors="replace")
        if "ModuleNotFoundError" in text or "No module named" in text:
            hint = (
                " Some code could not import a module: the sandbox is offline and has only the"
                " standard library and pytest."
            )
        code = r.exit_code
        if code == 0:
            return out("passed", base)
        if code == 1:
            return out("failed", base + hint)
        if code == PYTEST_NO_TESTS:
            return out("skipped", "Not run: pytest collected no tests.")
        return out("error", f"pytest could not complete (exit code {code}). {base}{hint}".strip())

    def _cases(self, report: junit.ParsedReport | None) -> tuple[CaseResult, ...]:
        if report is None:
            return ()
        return tuple(
            CaseResult(
                name=self._clean(c.name) or "(unnamed)",
                status=c.status,
                suite=self._clean(c.suite),
                classname=self._clean(c.classname),
                duration_ms=c.duration_ms,
                message=self._clean(c.message),
                detail=self._clean(c.detail),
            )
            for c in report.cases
        )

    def _evidence(
        self,
        request: ExecutionRequest,
        spec: SandboxSpec,
        r: SandboxResult,
        command: commands.CheckCommand,
        raw_report: bytes | None,
        report: junit.ParsedReport | None,
        problem: str | None,
    ) -> tuple[EvidenceItem, ...]:
        s = self._settings
        cap = s.sandbox_output_cap_bytes
        lim = spec.limits
        manifest = {
            "schema": 2,
            "check_id": request.check_id,
            "attempt": request.attempt,
            "command": list(spec.command),
            "project_code": command.runs_project_code,
            "image": spec.image,
            "image_id": r.image_id,
            "runtime": spec.runtime or "default (runc)",
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
        if command.result_file:
            manifest["result_file"] = {
                "present": raw_report is not None,
                "valid": report is not None,
                "problem": problem,
                "cases": report.counts() if report else {},
                "cases_truncated": bool(report and report.truncated),
            }
        items = [
            evidence.log_item(
                "stdout.log", frames.strip(r.stdout), self._secrets, cap, r.stdout_truncated
            ),  # fmt: skip
            evidence.log_item("stderr.log", r.stderr, self._secrets, cap, r.stderr_truncated),
            evidence.manifest_item(manifest),
        ]
        if raw_report is not None and report is not None:
            clean = evidence.redact(raw_report, self._secrets)
            items.append(EvidenceItem("junit.xml", "report", "application/xml", clean))
        return tuple(items)
