"""Stub executor: executes nothing.

Stage 7 proves queueing, cancellation and recovery without running target code. To avoid
ever reporting a pass or fail that did not happen, every test is recorded as ``skipped``
with an explicit reason.
"""

import uuid
from collections.abc import Callable

from sentinel_ai.execution.interface import ExecutionOutcome, ExecutionRequest

NOT_EXECUTED = "Not executed: the sandboxed executor is not available yet (Stage 8)."


class StubExecutor:
    def execute(
        self, request: ExecutionRequest, should_stop: Callable[[], bool]
    ) -> ExecutionOutcome:
        if should_stop():
            return ExecutionOutcome("cancelled", "Stopped before it started.")
        return ExecutionOutcome("skipped", NOT_EXECUTED, duration_ms=0)

    def terminate(self, batch_id: uuid.UUID) -> bool:
        return True  # nothing is ever started


def create_executor(kind: str) -> StubExecutor:
    if kind != "stub":
        raise ValueError("unsupported executor")
    return StubExecutor()
