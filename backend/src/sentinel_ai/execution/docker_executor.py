"""Sandboxed executor (Stage 8): the Stage 7 ``Executor`` backed by disposable containers.

For each planned test it looks up a fixed command by catalog check id, re-verifies the source
archive (project ownership was checked by the worker; here the hash and the archive headers),
sends it to a locked-down container over stdin, and turns the container's real exit state into
a result plus evidence. Network is always disabled. Checks without a runner yet are recorded
as skipped, and checks that need a network target are blocked, before anything starts.
"""

import io
import ipaddress
import logging
import secrets
import socket
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from sentinel_ai.core.config import Settings
from sentinel_ai.execution import (
    bandit_report,
    commands,
    dependency_report,
    evidence,
    frames,
    junit,
    scan_report,
    semgrep_report,
    zap_report,
)
from sentinel_ai.execution.docker_runner import DockerRunner, SandboxResult
from sentinel_ai.execution.interface import (
    CaseResult,
    EvidenceItem,
    ExecutionOutcome,
    ExecutionRequest,
    FindingResult,
    ScanOutcome,
)
from sentinel_ai.execution.sandbox_spec import (
    RESULT_MAX_BYTES,
    EgressSpec,
    SandboxLimits,
    SandboxSpec,
)
from sentinel_ai.services.archive import (
    ArchiveLimits,
    ArchiveRejected,
    inspect_archive,
    open_archive,
)
from sentinel_ai.services.artifact_store import ArtifactStore, sha256_bytes
from sentinel_ai.services.source_validation import (
    SourceRejected,
    is_global_address,
    require_public_host,
)

logger = logging.getLogger(__name__)

BANDIT_ISSUES_FOUND = 1
EXIT_REJECTED = 70  # the in-container runner refused the archive
PYTEST_NO_TESTS = 5
ADVISORY_LABEL = "sentinel.advisories.fetched_at"
# Exit codes that mean "the scanner ran to its own end" (anything else is an error).
SCAN_OK_EXITS = {"semgrep": (0, 1), "dependency_audit": (0,), "zap": (0, 1, 2)}
SCAN_LABELS = {"semgrep": "Semgrep", "dependency_audit": "The dependency audit", "zap": "ZAP"}
Resolver = Callable[[str], list[str]]
Report = junit.ParsedReport | bandit_report.ParsedBandit | scan_report.ParsedScan


def system_resolver(host: str) -> list[str]:
    """Addresses the worker's own resolver returns for ``host`` (empty when it cannot)."""
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError):
        return []
    return sorted({str(info[4][0]) for info in infos})


class _Prepared:
    """Per-run facts the executor derived itself (never from the sandbox)."""

    def __init__(self) -> None:
        self.argv: tuple[str, ...] = ()
        self.egress: EgressSpec | None = None
        self.host: str | None = None
        self.url: str | None = None
        self.advisory_fetched_at: str | None = None


class DockerSandboxExecutor:
    def __init__(
        self,
        settings: Settings,
        runner: DockerRunner | None = None,
        resolver: Resolver | None = None,
    ) -> None:
        self._settings = settings
        self._resolver = resolver or system_resolver
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
        prepared = _Prepared()
        prepared.argv = argv
        refusal = self._prepare(request, command, prepared)
        if refusal is not None:
            return refusal
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
            request, command, prepared, requested_timeout, extract=archive is not None, nonce=nonce
        )
        result = self._runner.run(spec, archive, should_stop)
        return self._outcome(request, spec, result, command, nonce, prepared)

    def terminate(self, batch_id: uuid.UUID) -> bool:
        return self._runner.cleanup_batch(batch_id)

    def sweep(self) -> int:
        s = self._settings
        return self._runner.sweep(s.sandbox_test_timeout_seconds + s.job_cancel_grace_seconds + 120)

    # ---- internals ---------------------------------------------------------------------------

    def _image(self, command: commands.CheckCommand) -> str:
        s = self._settings
        if command.image == commands.IMAGE_SCANNER:
            return s.sandbox_scanner_image
        if command.image == commands.IMAGE_ZAP:
            assert s.sandbox_zap_image is not None  # _prepare refuses a ZAP run without it
            return s.sandbox_zap_image
        return s.sandbox_image

    def _limits(
        self, request: ExecutionRequest, requested: int | None, command: commands.CheckCommand
    ) -> SandboxLimits:
        s = self._settings
        base = SandboxLimits(
            cpus=s.sandbox_cpus,
            memory_mb=s.sandbox_memory_mb,
            pids=s.sandbox_pids,
            workspace_mb=s.sandbox_workspace_mb,
            tmp_mb=s.sandbox_tmp_mb,
            timeout_seconds=s.sandbox_test_timeout_seconds,
            max_extract_mb=s.sandbox_max_extract_mb,
            max_file_mb=s.sandbox_max_file_mb,
            max_files=s.zip_max_files,
            max_zip_bytes=s.upload_max_mb * 1024 * 1024,
            output_cap_bytes=s.sandbox_output_cap_bytes,
        )
        if command.image == commands.IMAGE_ZAP:  # a JVM: more memory and threads, no source
            base = replace(
                base, memory_mb=s.sandbox_zap_memory_mb, pids=s.sandbox_zap_pids,
                tmp_mb=s.sandbox_zap_tmp_mb, workspace_mb=s.sandbox_zap_workspace_mb,
                timeout_seconds=s.sandbox_zap_timeout_seconds,
            )  # fmt: skip
        timeout = min(request.timeout_seconds, base.timeout_seconds, requested or 10**9)
        return replace(base, timeout_seconds=timeout)

    def _spec(
        self,
        request: ExecutionRequest,
        command: commands.CheckCommand,
        prepared: _Prepared,
        requested_timeout: int | None,
        *,
        extract: bool,
        nonce: str | None,
    ) -> SandboxSpec:
        s = self._settings
        return SandboxSpec(
            image=self._image(command),
            scope=s.sandbox_scope,
            run_id=request.run_id,
            batch_id=request.batch_id,
            command=prepared.argv,
            limits=self._limits(request, requested_timeout, command),
            extract_source=extract,
            runtime=s.sandbox_runtime,
            result_file=command.result_file,
            result_nonce=nonce,
            egress=prepared.egress,
        )

    # ---- checks that must pass before any container exists ------------------------------------

    def _prepare(
        self, request: ExecutionRequest, command: commands.CheckCommand, prepared: _Prepared
    ) -> ExecutionOutcome | None:
        if command.needs_target:
            return self._prepare_zap(request, command, prepared)
        if command.kind == "dependency_audit":
            return self._check_advisory_age(command, prepared)
        return None

    def _check_advisory_age(
        self, command: commands.CheckCommand, prepared: _Prepared
    ) -> ExecutionOutcome | None:
        """Stale advisory data would turn "no known issues" into a false all-clear, so the
        audit refuses to run on it. The date is the image's build label, not the container's."""
        raw = self._runner.image_label(self._image(command), ADVISORY_LABEL)
        try:
            fetched = datetime.fromisoformat((raw or "").replace("Z", "+00:00"))
            if fetched.tzinfo is None:
                raise ValueError
        except ValueError:
            return ExecutionOutcome(
                "blocked",
                "Blocked: the sandbox image has no advisory data date. Build it with "
                "`make advisories sandbox-image`.",
            )
        age = (datetime.now(UTC) - fetched).days
        limit = self._settings.dependency_advisory_max_age_days
        if age > limit:
            return ExecutionOutcome(
                "blocked",
                f"Blocked: the advisory data in the sandbox image is {age} days old "
                f"(limit {limit}). Refresh it with `make advisories sandbox-image`.",
            )
        prepared.advisory_fetched_at = fetched.isoformat()
        return None

    def _prepare_zap(
        self, request: ExecutionRequest, command: commands.CheckCommand, prepared: _Prepared
    ) -> ExecutionOutcome | None:
        s = self._settings
        if not (s.sandbox_zap_image and s.sandbox_zap_network and s.sandbox_zap_egress_attested):
            return ExecutionOutcome(
                "blocked",
                "Blocked: OWASP ZAP is not enabled on this deployment (it needs a ZAP image and "
                "an operator-attested, egress-restricted network).",
            )
        target = request.target
        if target is None:
            return ExecutionOutcome("blocked", "Blocked: the check has no authorized target.")
        if target.environment not in ("development", "staging"):
            return ExecutionOutcome(
                "blocked", "Blocked: ZAP runs only against development or staging targets."
            )
        try:
            url = commands.zap_url(target.url, request.parameters)
            host = (urlsplit(url).hostname or "").lower()
            port = urlsplit(url).port
            if port is not None and not 1 <= port <= 65535:
                raise commands.InvalidParameters("the target port is out of range")
            try:
                ipaddress.ip_address(host)
            except ValueError:
                pass
            else:
                raise commands.InvalidParameters("the target must be a DNS name, not an address")
            require_public_host(host)
            argv = commands.with_target(prepared.argv, url)
        except (commands.InvalidParameters, SourceRejected) as exc:
            return ExecutionOutcome("blocked", f"Blocked: {exc}.")
        # Resolve here, in the trusted worker, and pin the answer: the container gets no
        # working DNS, so it cannot be steered elsewhere by a changing or hostile record.
        addresses = self._resolver(host)
        try:
            parsed = [ipaddress.ip_address(a) for a in addresses]
        except ValueError:
            parsed = []
        if not parsed:
            return ExecutionOutcome("blocked", "Blocked: the target host could not be resolved.")
        if not all(is_global_address(ip) for ip in parsed):
            return ExecutionOutcome(
                "blocked", "Blocked: the target host resolves to a non-public address."
            )
        egress = EgressSpec(network=s.sandbox_zap_network, host=host, ip=str(parsed[0]))
        try:
            egress.validate()
        except ValueError:
            return ExecutionOutcome("blocked", "Blocked: the target host cannot be pinned safely.")
        prepared.argv, prepared.egress, prepared.host, prepared.url = argv, egress, host, url
        return None

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
        self,
        command: commands.CheckCommand,
        nonce: str | None,
        r: SandboxResult,
        prepared: _Prepared,
    ) -> tuple[bytes | None, Report | None, str | None]:
        """(raw result file, parsed report, problem). Only for runners that produce one."""
        if not command.result_file or nonce is None:
            return None, None, None
        raw = frames.extract(r.stdout_tail or r.stdout, nonce, RESULT_MAX_BYTES)
        if raw is None:
            return None, None, "no result file was produced"
        try:
            if command.kind == "bandit":
                return raw, bandit_report.parse(raw), None
            if command.kind == "semgrep":
                return raw, semgrep_report.parse(raw), None
            if command.kind == "dependency_audit":
                return raw, dependency_report.parse(raw), None
            if command.kind == "zap":
                assert prepared.host is not None  # set by _prepare_zap
                return raw, zap_report.parse(raw, host=prepared.host, active=command.active), None
            return raw, junit.parse(raw), None
        except (junit.InvalidReport, bandit_report.InvalidReport, scan_report.InvalidReport) as exc:
            return None, None, str(exc)

    def _outcome(
        self,
        request: ExecutionRequest,
        spec: SandboxSpec,
        r: SandboxResult,
        command: commands.CheckCommand,
        nonce: str | None,
        prepared: _Prepared,
    ) -> ExecutionOutcome:
        raw, report, problem = self._report(command, nonce, r, prepared)
        items = self._evidence(request, spec, r, command, raw, report, problem, prepared)
        cases = self._cases(report) if isinstance(report, junit.ParsedReport) else ()
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
            assert report is None or isinstance(report, junit.ParsedReport)
            return self._pytest_outcome(r, report, problem, out)
        if command.kind == "bandit":
            assert report is None or isinstance(report, bandit_report.ParsedBandit)
            outcome = self._bandit_outcome(r, report, problem, out)
            if isinstance(report, bandit_report.ParsedBandit) and r.exit_code in (
                0,
                BANDIT_ISSUES_FOUND,
            ):
                # Only a scan that ran to its own end counts; a killed, timed-out or
                # cancelled sandbox returned above and never reaches ingestion.
                outcome = replace(outcome, scan=self._scan(report))
            return outcome
        if command.kind in SCAN_OK_EXITS:
            assert report is None or isinstance(report, scan_report.ParsedScan)
            outcome = self._scan_outcome(command.kind, r, report, problem, out)
            if report is not None and r.exit_code in SCAN_OK_EXITS[command.kind]:
                if outcome.status in ("passed", "failed"):  # a run that reached its own end
                    outcome = replace(outcome, scan=self._generic_scan(report))
            return outcome
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

    def _bandit_outcome(
        self,
        r: SandboxResult,
        report: bandit_report.ParsedBandit | None,
        problem: str | None,
        out: Callable[[str, str], ExecutionOutcome],
    ) -> ExecutionOutcome:
        """Status comes from the exit state and a valid report. "passed" is only reported for
        a scan that produced a valid report with no findings: a missing or unreadable report
        is an error, never a clean bill of health."""
        if r.exit_code not in (0, BANDIT_ISSUES_FOUND):
            return out("error", f"Bandit could not complete (exit code {r.exit_code}).")
        if report is None:
            return out("error", f"Bandit produced no usable report ({problem or 'unknown'}).")
        n = len(report.findings)
        unread = len(report.errors)
        notes = f" {unread} file(s) could not be analysed." if unread else ""
        if report.truncated:
            notes += f" Only the first {bandit_report.MAX_FINDINGS} findings were kept."
        if n == 0 and unread:
            return out("error", "Bandit analysed nothing it could report on." + notes)
        if n == 0:
            return out("passed", "Bandit reported no issues." + notes)
        word = "issue" if n == 1 else "issues"
        return out("failed", f"Bandit reported {n} {word}; each is unverified." + notes)

    def _scan_outcome(
        self,
        kind: str,
        r: SandboxResult,
        report: scan_report.ParsedScan | None,
        problem: str | None,
        out: Callable[[str, str], ExecutionOutcome],
    ) -> ExecutionOutcome:
        """Same rule as Bandit: "passed" only for a valid report with no findings and no
        problems. A missing report, an unexpected exit code or a tool that reported problems
        is an error, never a clean bill of health."""
        label = SCAN_LABELS[kind]
        if r.exit_code not in SCAN_OK_EXITS[kind]:
            if kind == "dependency_audit" and r.exit_code == 3:
                return out("error", "The sandbox image has no advisory data to audit against.")
            return out("error", f"{label} could not complete (exit code {r.exit_code}).")
        if report is None:
            return out("error", f"{label} produced no usable report ({problem or 'unknown'}).")
        if kind == "dependency_audit" and not dict(report.extra).get("lockfiles"):
            if not report.errors:
                return out("skipped", "Not run: no supported lockfile was found to audit.")
        n = len(report.findings)
        notes = ""
        if report.truncated:
            notes += f" Only the first {scan_report.MAX_FINDINGS} findings were kept."
        if report.errors and n == 0:
            return out(
                "error",
                f"{label} finished with {len(report.errors)} problem(s) and no findings, so the "
                f"result is not a clean pass: {report.errors[0]}",
            )
        if report.errors:
            notes += f" {len(report.errors)} problem(s) were reported; the scan is incomplete."
        if n == 0:
            return out("passed", f"{label} reported no issues.{notes}")
        word = "issue" if n == 1 else "issues"
        return out("failed", f"{label} reported {n} {word}; each is unverified.{notes}")

    def _generic_scan(self, report: scan_report.ParsedScan) -> ScanOutcome:
        return ScanOutcome(
            tool=report.tool,
            findings=tuple(
                replace(
                    f,
                    title=self._clean(f.title) or f.rule_id,
                    message=self._clean(f.message) or "",
                    component=self._clean(f.component),
                )
                for f in report.findings
            ),
            complete=report.complete,
            limitations=report.limitations,
            lines_scanned=report.lines_scanned,
        )

    def _scan(self, report: bandit_report.ParsedBandit) -> ScanOutcome:
        return ScanOutcome(
            tool="bandit",
            findings=tuple(
                FindingResult(
                    tool="bandit",
                    rule_id=f.rule_id,
                    title=self._clean(f"{f.rule_id}: {f.rule_name.replace('_', ' ')}") or f.rule_id,
                    severity=f.severity,
                    confidence=f.confidence,
                    path=f.path,
                    line=f.line,
                    message=self._clean(f.message) or "",
                    fingerprint=f.fingerprint,
                    cwe=f.cwe,
                )
                for f in report.findings
            ),
            complete=not report.errors and not report.truncated,
            limitations=bandit_report.LIMITATIONS,
            lines_scanned=report.lines_scanned,
        )

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
        report: Report | None,
        problem: str | None,
        prepared: _Prepared,
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
            "network": "none"
            if spec.egress is None
            else {
                "name": spec.egress.network,
                "host": spec.egress.host,
                "pinned_ip": spec.egress.ip,
                "dns": "black hole (only the pinned host resolves)",
            },
            "target_url": prepared.url,
            "advisory_data_fetched_at": prepared.advisory_fetched_at,
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
                "cases": report.counts() if isinstance(report, junit.ParsedReport) else {},
                "cases_truncated": bool(report and report.truncated),
            }
        items = [
            evidence.log_item(
                "stdout.log", frames.strip(r.stdout), self._secrets, cap, r.stdout_truncated
            ),  # fmt: skip
            evidence.log_item("stderr.log", r.stderr, self._secrets, cap, r.stderr_truncated),
            evidence.manifest_item(manifest),
        ]
        if raw_report is not None and isinstance(report, junit.ParsedReport):
            clean = evidence.redact(raw_report, self._secrets)
            items.append(EvidenceItem("junit.xml", "report", "application/xml", clean))
        elif isinstance(report, scan_report.ParsedScan):
            clean = evidence.redact(scan_report.sanitized(report), self._secrets)
            items.append(EvidenceItem(f"{report.tool}.json", "report", "application/json", clean))
        elif isinstance(report, bandit_report.ParsedBandit):
            # Re-serialized from validated fields: Bandit's own file also quotes source code.
            clean = evidence.redact(bandit_report.sanitized_report(report), self._secrets)
            items.append(EvidenceItem("bandit.json", "report", "application/json", clean))
        return tuple(items)
