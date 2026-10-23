"""Celery entry point for the hard-kill test: a worker whose executor never finishes by itself.

Used as ``celery -A slow_worker worker``; the test SIGKILLs the process mid-batch. It polls
``should_stop`` (which renews the lease), exactly as a real executor must.
"""

import time
from collections.abc import Callable

from sentinel_ai.execution.interface import ExecutionOutcome, ExecutionRequest
from sentinel_ai.execution.stub import StubExecutor
from sentinel_ai.jobs import tasks


class SlowExecutor(StubExecutor):
    def execute(
        self, request: ExecutionRequest, should_stop: Callable[[], bool]
    ) -> ExecutionOutcome:
        while not should_stop():
            time.sleep(0.2)
        return ExecutionOutcome("cancelled", "stopped")


tasks.create_executor = lambda kind: SlowExecutor()  # type: ignore[assignment]
from sentinel_ai.jobs.worker import app  # noqa: E402,F401  (registers the tasks on this app)
