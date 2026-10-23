"""Executor interface (Stage 7). The sandboxed implementation arrives in Stage 8.

The job layer depends only on this protocol. A request carries identifiers and the catalog
check id, never a command line, credentials or host paths; the executor looks up what to
run from trusted catalog data inside its own boundary.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

# Statuses an executor may report. They are a subset of test_results.status; the worker
# adds ``blocked`` (policy) and ``cancelled`` itself.
OUTCOME_STATUSES = frozenset(
    {"passed", "failed", "error", "skipped", "timed_out", "cancelled", "failed_to_start"}
)


@dataclass(frozen=True)
class ExecutionRequest:
    run_id: uuid.UUID
    batch_id: uuid.UUID
    planned_test_id: uuid.UUID
    check_id: str
    attempt: int
    timeout_seconds: int


@dataclass(frozen=True)
class ExecutionOutcome:
    status: str
    summary: str
    exit_code: int | None = None
    duration_ms: int | None = None


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
