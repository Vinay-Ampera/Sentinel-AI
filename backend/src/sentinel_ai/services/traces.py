"""The correlation view of one W3C trace id (ADR-0011): which platform workflows carry it (a
test run, an assistant run with its steps) and which reported events share it.

Correlation is by identifier only: an event is shown here because the application reported the
same trace id, never because of timing, and nothing here claims one caused the other. Every
lookup is scoped by project."""

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from sentinel_ai.core.config import Settings
from sentinel_ai.core.errors import DomainError
from sentinel_ai.repositories import agent_runs
from sentinel_ai.repositories import observability as repo

TRACE_ID = re.compile(r"^[0-9a-f]{32}$")
MAX_EVENTS = 50
LIMITS = [
    "Events appear here only if the application reported this exact trace id; Sentinel does not "
    "collect spans and cannot see calls that were not reported.",
    "Sharing a trace id shows the events belong to the same operation as the run, not that one "
    "caused the other.",
]


def trace_view(
    db: Session, settings: Settings, project_id: uuid.UUID, trace_id: str
) -> dict[str, Any]:
    if not TRACE_ID.match(trace_id):
        raise DomainError(422, "validation_failed", "A trace id is 32 lowercase hex characters")
    runs = repo.runs_by_trace(db, project_id, trace_id)
    assistant = repo.agent_runs_by_trace(db, project_id, trace_id)
    since = datetime.now(UTC) - timedelta(days=settings.event_sample_retention_days)
    samples = repo.samples_by_trace(db, project_id, trace_id, MAX_EVENTS, since)
    if not (runs or assistant or samples):
        raise DomainError(404, "not_found", "Trace not found")
    return {
        "trace_id": trace_id,
        "runs": runs,
        "assistant_runs": [
            {**a, "steps": [
                {"seq": s.seq, "node": s.node, "kind": s.kind, "outcome": s.outcome,
                 "created_at": s.created_at}
                for s in agent_runs.list_steps(db, a["id"])
            ]}
            for a in assistant
        ],
        "events": samples,
        "limits": LIMITS,
    }  # fmt: skip
