"""Executor interface (Stage 7; the Docker sandbox implements it in Stage 8).

The job layer depends only on this protocol. A request carries identifiers, the catalog
check id and a verified reference to the source archive, never a command line, credentials or
host paths; the executor looks up what to run from trusted catalog data inside its own
boundary.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

# Statuses an executor may report (a subset of test_results.status). ``blocked`` means it
# refused to run the check before starting anything.
OUTCOME_STATUSES = frozenset(
    {"passed", "failed", "error", "skipped", "blocked", "timed_out", "cancelled", "failed_to_start"}
)


@dataclass(frozen=True)
class WorkspaceRef:
    """A source archive the worker verified belongs to the run's project. The executor reads
    it from the artifact store by key and re-checks the hash before use."""

    storage_key: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class ExecutionRequest:
    run_id: uuid.UUID
    batch_id: uuid.UUID
    planned_test_id: uuid.UUID
    check_id: str
    attempt: int
    timeout_seconds: int
    project_id: uuid.UUID | None = None
    workspace: WorkspaceRef | None = None
    # Plan-time parameters (already validated and frozen with the approved plan). The
    # executor validates them again before use.
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidenceItem:
    """A file of evidence produced by an execution. Content is already redacted and capped;
    ``name`` is one of a fixed set, never taken from the sandbox."""

    name: str
    kind: str  # an artifacts.kind value: "log" or "report"
    content_type: str
    data: bytes


@dataclass(frozen=True)
class CaseResult:
    """One case a runner reported (for pytest, one test function). Text is untrusted:
    redacted, control characters removed and clipped before it gets here."""

    name: str
    status: str  # passed | failed | error | skipped
    suite: str | None = None
    classname: str | None = None
    duration_ms: int | None = None
    message: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class ExecutionOutcome:
    status: str
    summary: str
    exit_code: int | None = None
    duration_ms: int | None = None
    evidence: tuple[EvidenceItem, ...] = ()
    cases: tuple[CaseResult, ...] = ()


class Executor(Protocol):
    def execute(
        self, request: ExecutionRequest, should_stop: Callable[[], bool]
    ) -> ExecutionOutcome:
        """Run one planned test. ``should_stop`` becomes true when cancellation or a timeout
        is requested; the executor must then terminate its sandbox and return promptly."""
        ...

    def terminate(self, batch_id: uuid.UUID) -> bool:
        """Best-effort termination of anything still running for the batch. True when
        nothing remains (or nothing ever ran); False when termination is unconfirmed."""
        ...
