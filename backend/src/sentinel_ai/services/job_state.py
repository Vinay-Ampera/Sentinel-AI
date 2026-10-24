"""State changes shared by the API, the worker and the reconciler (Stage 7).

Every change is a conditional transition (see ``repositories.runs``) plus an append-only
``job_events`` row written in the same transaction, so history and status cannot diverge.
Run status is derived from batch status; nothing here trusts the queue.
"""

import logging
import random
import uuid
from typing import Any

from sqlalchemy.orm import Session

from sentinel_ai.repositories import runs
from sentinel_ai.repositories.runs import TERMINAL, BatchRecord, RunRecord
from sentinel_ai.services import alerts, audit
from sentinel_ai.services.audit import RequestContext

logger = logging.getLogger(__name__)

SYSTEM_CONTEXT = RequestContext(request_id=None, ip_address=None, user_agent=None)
SUMMARY_LIMIT = 2000
MAX_BACKOFF_SECONDS = 300.0


def clip(text: str | None) -> str | None:
    return None if text is None else text[:SUMMARY_LIMIT]


def batch_to(
    db: Session,
    batch: BatchRecord,
    to_status: str,
    *,
    event_type: str = "transition",
    worker_id: str | None = None,
    actor_user_id: uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
    error_code: str | None = None,
    error_summary: str | None = None,
    finish: bool = False,
    start: bool = False,
) -> bool:
    """Move ``batch`` from the status it was read with. False = someone else moved it first."""
    ok = runs.transition_batch(
        db,
        batch.id,
        batch.status,
        to_status,
        finish=finish,
        start=start,
        error_code=error_code,
        error_summary=clip(error_summary),
    )
    if ok:
        runs.insert_event(
            db,
            batch.run_id,
            event_type,
            batch_id=batch.id,
            from_status=batch.status,
            to_status=to_status,
            actor_user_id=actor_user_id,
            worker_id=worker_id,
            detail={
                "attempt": batch.attempt,
                **(detail or {}),
                **({"error": error_code} if error_code else {}),
            },
        )
    return ok


def requeue_batch(
    db: Session,
    batch: BatchRecord,
    *,
    base_backoff: float,
    worker_id: str | None,
    reason: str,
) -> bool:
    """Bounded retry: back to ``queued`` with attempt + 1 after exponential backoff + jitter."""
    backoff = min(
        MAX_BACKOFF_SECONDS, base_backoff * (2 ** (batch.attempt - 1)) * random.uniform(0.5, 1.5)
    )
    ok = runs.transition_batch(
        db, batch.id, batch.status, "queued", requeue=True, backoff_seconds=backoff
    )
    if ok:
        runs.insert_event(
            db,
            batch.run_id,
            "retry_scheduled",
            batch_id=batch.id,
            from_status=batch.status,
            to_status="queued",
            worker_id=worker_id,
            detail={
                "reason": reason,
                "next_attempt": batch.attempt + 1,
                "max_attempts": batch.max_attempts,
                "backoff_seconds": round(backoff, 2),
            },
        )
    return ok


def mark_unrun(db: Session, run: RunRecord, batch: BatchRecord, status: str, summary: str) -> int:
    """Record the batch's tests that never produced a result, so none is silently missing
    ("not run" is stated, never a pass). Idempotent per (batch, test, attempt)."""
    done = runs.finished_test_ids(db, batch.id)
    count = 0
    for test_id in runs.list_items(db, batch.id):
        if test_id in done:
            continue
        if runs.insert_result(
            db,
            run_id=run.id,
            batch_id=batch.id,
            planned_test_id=test_id,
            attempt=batch.attempt,
            status=status,
            summary=summary,
        ):
            count += 1
    return count


def derive_run_status(batch_statuses: list[str]) -> str:
    unique = set(batch_statuses)
    if unique == {"completed"}:
        return "completed"
    if "failed" in unique:
        return "failed"
    if "timed_out" in unique:
        return "timed_out"
    return "cancelled"


def _allowed_final(status: str, target: str) -> bool:
    return target in {
        "queued": {"cancelled", "timed_out"},
        "dispatched": {"failed", "cancelled", "timed_out"},
        "running": {"completed", "failed", "timed_out"},
        "cancel_requested": {"cancelled", "completed", "failed", "timed_out"},
    }.get(status, set())


def _raise_run_alert(db: Session, run_id: uuid.UUID) -> None:
    """Internal alert for a failed run (ADR-0011). Best effort in a savepoint: an alerting
    problem must never fail or roll back the run's own transition."""
    try:
        with db.begin_nested():
            alerts.evaluate_run(db, None, run_id)
    except Exception as exc:
        logger.warning("run alert evaluation failed (%s)", type(exc).__name__)


def finalize_run(db: Session, run_id: uuid.UUID, *, worker_id: str | None = None) -> str | None:
    """If every batch is terminal, give the run its derived final status. Returns the new
    status, or None when nothing changed. Safe to call repeatedly and concurrently."""
    run = runs.get_run(db, run_id, for_update=True)
    if run is None or run.status in TERMINAL:
        return None
    batches = runs.list_batches(db, run_id)
    if not batches or any(b.status not in TERMINAL for b in batches):
        return None
    target = derive_run_status([b.status for b in batches])
    current = run.status
    if current in ("queued", "dispatched") and target in ("completed", "failed"):
        # The run never recorded a start (e.g. a worker lost during claim); keep history valid.
        for step_from, step_to in (("queued", "dispatched"), ("dispatched", "running")):
            if current == step_from and runs.transition_run(
                db, run_id, step_from, step_to, start=step_to == "running"
            ):
                runs.insert_event(
                    db, run_id, "transition", from_status=step_from, to_status=step_to
                )
                current = step_to
    if not _allowed_final(current, target):
        target = "failed" if _allowed_final(current, "failed") else target
    failed = next((b for b in batches if b.status == "failed"), None)
    code = failed.error_code if failed and target == "failed" else None
    summary = failed.error_summary if failed and target == "failed" else None
    if not runs.transition_run(
        db, run_id, current, target, finish=True, error_code=code, error_summary=summary
    ):
        return None
    runs.insert_event(
        db,
        run_id,
        "transition",
        from_status=current,
        to_status=target,
        worker_id=worker_id,
        detail={
            "batches": {
                s: [b.status for b in batches].count(s) for s in set(b.status for b in batches)
            }
        },
    )
    audit.record(
        db,
        SYSTEM_CONTEXT,
        action="run.finish",
        outcome="success",
        actor_type="worker" if worker_id else "system",
        project_id=run.project_id,
        target_type="run",
        target_id=str(run_id),
        detail={"status": target},
    )
    _raise_run_alert(db, run_id)
    return target
