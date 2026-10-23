"""All SQL for test runs, batches, batch items, results and job events (Stage 7).

Status changes go through ``transition_run`` / ``transition_batch``: each is a single
conditional ``UPDATE ... WHERE status = :from`` so concurrent actors (API cancel, worker,
reconciler) cannot both win, and the database trigger from migration 0002 still rejects any
edge that is not in ``state_transitions``. Time comparisons use the database clock.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

ACTIVE = ("queued", "dispatched", "running", "cancel_requested")
CLAIMED = ("dispatched", "running", "cancel_requested")
TERMINAL = ("completed", "failed", "cancelled", "timed_out")

_RUN = (
    "id, project_id, plan_id, parent_run_id, kind, status, idempotency_key, requested_by, "
    "timeout_seconds, cancel_requested_at, cancel_requested_by, started_at, finished_at, "
    "error_code, error_summary, created_at, updated_at"
)
_BATCH = (
    "id, run_id, ordinal, status, attempt, max_attempts, timeout_seconds, queue_task_id, "
    "worker_id, started_at, finished_at, error_code, error_summary, heartbeat_at, "
    "lease_expires_at, not_before, created_at, updated_at"
)
_RESULT = (
    "id, run_id, batch_id, planned_test_id, attempt, status, summary, exit_code, duration_ms, "
    "started_at, finished_at, created_at"
)


@dataclass(frozen=True)
class RunRecord:
    id: uuid.UUID
    project_id: uuid.UUID
    plan_id: uuid.UUID
    parent_run_id: uuid.UUID | None
    kind: str
    status: str
    idempotency_key: str | None
    requested_by: uuid.UUID
    timeout_seconds: int
    cancel_requested_at: datetime | None
    cancel_requested_by: uuid.UUID | None
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_summary: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class BatchRecord:
    id: uuid.UUID
    run_id: uuid.UUID
    ordinal: int
    status: str
    attempt: int
    max_attempts: int
    timeout_seconds: int
    queue_task_id: str | None
    worker_id: str | None
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_summary: str | None
    heartbeat_at: datetime | None
    lease_expires_at: datetime | None
    not_before: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ResultRecord:
    id: uuid.UUID
    run_id: uuid.UUID
    batch_id: uuid.UUID
    planned_test_id: uuid.UUID
    attempt: int
    status: str
    summary: str | None
    exit_code: int | None
    duration_ms: int | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class EventRecord:
    id: int
    run_id: uuid.UUID
    batch_id: uuid.UUID | None
    event_type: str
    from_status: str | None
    to_status: str | None
    actor_user_id: uuid.UUID | None
    worker_id: str | None
    detail: dict[str, Any]
    created_at: datetime


# ---- runs ----------------------------------------------------------------------------------


def insert_run(
    db: Session,
    *,
    project_id: uuid.UUID,
    plan_id: uuid.UUID,
    requested_by: uuid.UUID,
    timeout_seconds: int,
    idempotency_key: str | None,
) -> RunRecord:
    row = db.execute(
        text(
            "INSERT INTO public.test_runs (project_id, plan_id, requested_by, timeout_seconds, "
            f"idempotency_key) VALUES (:p, :pl, :u, :t, :k) RETURNING {_RUN}"
        ),
        {
            "p": project_id,
            "pl": plan_id,
            "u": requested_by,
            "t": timeout_seconds,
            "k": idempotency_key,
        },
    ).one()
    return RunRecord(**row._mapping)


def get_run(db: Session, run_id: uuid.UUID, *, for_update: bool = False) -> RunRecord | None:
    sql = f"SELECT {_RUN} FROM public.test_runs WHERE id = :i" + (
        " FOR UPDATE" if for_update else ""
    )
    row = db.execute(text(sql), {"i": run_id}).first()
    return RunRecord(**row._mapping) if row else None


def get_run_by_key(db: Session, project_id: uuid.UUID, key: str) -> RunRecord | None:
    row = db.execute(
        text(f"SELECT {_RUN} FROM public.test_runs WHERE project_id = :p AND idempotency_key = :k"),
        {"p": project_id, "k": key},
    ).first()
    return RunRecord(**row._mapping) if row else None


def active_run_for_plan(db: Session, plan_id: uuid.UUID) -> RunRecord | None:
    row = db.execute(
        text(
            f"SELECT {_RUN} FROM public.test_runs WHERE plan_id = :p "
            "AND status IN ('queued', 'dispatched', 'running', 'cancel_requested') LIMIT 1"
        ),
        {"p": plan_id},
    ).first()
    return RunRecord(**row._mapping) if row else None


def list_runs(db: Session, project_id: uuid.UUID, limit: int) -> list[RunRecord]:
    rows = db.execute(
        text(
            f"SELECT {_RUN} FROM public.test_runs WHERE project_id = :p "
            "ORDER BY created_at DESC, id LIMIT :n"
        ),
        {"p": project_id, "n": limit},
    ).all()
    return [RunRecord(**r._mapping) for r in rows]


def transition_run(
    db: Session,
    run_id: uuid.UUID,
    from_status: str,
    to_status: str,
    *,
    start: bool = False,
    finish: bool = False,
    error_code: str | None = None,
    error_summary: str | None = None,
    cancel_by: uuid.UUID | None = None,
) -> bool:
    sets = ["status = :to"]
    if start:
        sets.append("started_at = COALESCE(started_at, now())")
    if finish:
        sets.append("finished_at = now()")
    if error_code is not None:
        sets.append("error_code = :ec, error_summary = :es")
    if cancel_by is not None:
        sets.append("cancel_requested_at = now(), cancel_requested_by = :cb")
    result = db.execute(
        text(f"UPDATE public.test_runs SET {', '.join(sets)} WHERE id = :i AND status = :from"),
        {
            "i": run_id,
            "from": from_status,
            "to": to_status,
            "ec": error_code,
            "es": error_summary,
            "cb": cancel_by,
        },
    )
    return result.rowcount == 1  # type: ignore[attr-defined, no-any-return]


def run_ids_overdue(db: Session, queue_wait_seconds: int) -> list[uuid.UUID]:
    """Active runs past their own timeout, or queued for too long without ever starting."""
    rows = db.execute(
        text(
            "SELECT id FROM public.test_runs WHERE status IN "
            "('queued', 'dispatched', 'running', 'cancel_requested') AND ("
            " (started_at IS NOT NULL AND started_at + make_interval(secs => timeout_seconds)"
            "  < clock_timestamp())"
            " OR (started_at IS NULL AND created_at + make_interval(secs => :w) < clock_timestamp())"
            ") ORDER BY created_at"
        ),
        {"w": queue_wait_seconds},
    ).all()
    return [r[0] for r in rows]


def run_ids_all_batches_terminal(db: Session) -> list[uuid.UUID]:
    rows = db.execute(
        text(
            "SELECT r.id FROM public.test_runs r WHERE r.status IN "
            "('queued', 'dispatched', 'running', 'cancel_requested') "
            "AND EXISTS (SELECT 1 FROM public.test_batches b WHERE b.run_id = r.id) "
            "AND NOT EXISTS (SELECT 1 FROM public.test_batches b WHERE b.run_id = r.id "
            " AND b.status NOT IN ('completed', 'failed', 'cancelled', 'timed_out'))"
        )
    ).all()
    return [r[0] for r in rows]


# ---- batches and items ---------------------------------------------------------------------


def insert_batch(
    db: Session, run_id: uuid.UUID, ordinal: int, *, max_attempts: int, timeout_seconds: int
) -> BatchRecord:
    row = db.execute(
        text(
            "INSERT INTO public.test_batches (run_id, ordinal, max_attempts, timeout_seconds) "
            f"VALUES (:r, :o, :m, :t) RETURNING {_BATCH}"
        ),
        {"r": run_id, "o": ordinal, "m": max_attempts, "t": timeout_seconds},
    ).one()
    return BatchRecord(**row._mapping)


def insert_item(
    db: Session, batch_id: uuid.UUID, run_id: uuid.UUID, planned_test_id: uuid.UUID, ordinal: int
) -> None:
    db.execute(
        text(
            "INSERT INTO public.test_batch_items (batch_id, run_id, planned_test_id, ordinal) "
            "VALUES (:b, :r, :t, :o)"
        ),
        {"b": batch_id, "r": run_id, "t": planned_test_id, "o": ordinal},
    )


def list_items(db: Session, batch_id: uuid.UUID) -> list[uuid.UUID]:
    rows = db.execute(
        text(
            "SELECT planned_test_id FROM public.test_batch_items WHERE batch_id = :b ORDER BY ordinal"
        ),
        {"b": batch_id},
    ).all()
    return [r[0] for r in rows]


def get_batch(db: Session, batch_id: uuid.UUID, *, for_update: bool = False) -> BatchRecord | None:
    sql = f"SELECT {_BATCH} FROM public.test_batches WHERE id = :i" + (
        " FOR UPDATE" if for_update else ""
    )
    row = db.execute(text(sql), {"i": batch_id}).first()
    return BatchRecord(**row._mapping) if row else None


def list_batches(db: Session, run_id: uuid.UUID, *, for_update: bool = False) -> list[BatchRecord]:
    sql = f"SELECT {_BATCH} FROM public.test_batches WHERE run_id = :r ORDER BY ordinal" + (
        " FOR UPDATE" if for_update else ""
    )
    return [BatchRecord(**r._mapping) for r in db.execute(text(sql), {"r": run_id}).all()]


def transition_batch(
    db: Session,
    batch_id: uuid.UUID,
    from_status: str,
    to_status: str,
    *,
    start: bool = False,
    finish: bool = False,
    error_code: str | None = None,
    error_summary: str | None = None,
    claim_worker: str | None = None,
    lease_seconds: int | None = None,
    requeue: bool = False,
    backoff_seconds: float = 0.0,
) -> bool:
    """One conditional status change. ``claim_worker`` records the owner and starts the
    lease; ``requeue`` bumps the attempt and releases the batch for dispatch again (after
    ``backoff_seconds``); leaving a claimed state otherwise clears the lease."""
    sets = ["status = :to"]
    if claim_worker is not None:
        sets.append("worker_id = :w, heartbeat_at = clock_timestamp()")
    if lease_seconds is not None:
        sets.append("lease_expires_at = clock_timestamp() + make_interval(secs => :ls)")
    if start:
        sets.append("started_at = COALESCE(started_at, clock_timestamp())")
    if finish:
        sets.append("finished_at = clock_timestamp(), lease_expires_at = NULL")
    if requeue:
        sets.append(
            "attempt = attempt + 1, queue_task_id = NULL, worker_id = NULL, started_at = NULL, "
            "lease_expires_at = NULL, heartbeat_at = NULL, finished_at = NULL, "
            "error_code = NULL, error_summary = NULL, "
            "not_before = clock_timestamp() + make_interval(secs => :bo)"
        )
    if error_code is not None:
        sets.append("error_code = :ec, error_summary = :es")
    result = db.execute(
        text(f"UPDATE public.test_batches SET {', '.join(sets)} WHERE id = :i AND status = :from"),
        {
            "i": batch_id,
            "from": from_status,
            "to": to_status,
            "w": claim_worker,
            "ls": lease_seconds,
            "ec": error_code,
            "es": error_summary,
            "bo": backoff_seconds,
        },
    )
    return result.rowcount == 1  # type: ignore[attr-defined, no-any-return]


def claim_batch(
    db: Session, batch_id: uuid.UUID, task_id: str, worker_id: str, lease_seconds: int
) -> BatchRecord | None:
    """queued -> dispatched, only for the *latest* dispatch (matching ``queue_task_id``) of a
    batch that may run now. A duplicate or stale delivery matches nothing."""
    row = db.execute(
        text(
            "UPDATE public.test_batches SET status = 'dispatched', worker_id = :w, "
            "heartbeat_at = clock_timestamp(), "
            "lease_expires_at = clock_timestamp() + make_interval(secs => :ls) "
            "WHERE id = :i AND status = 'queued' AND queue_task_id = :t "
            "AND (not_before IS NULL OR not_before <= clock_timestamp()) "
            f"RETURNING {_BATCH}"
        ),
        {"i": batch_id, "t": task_id, "w": worker_id, "ls": lease_seconds},
    ).first()
    return BatchRecord(**row._mapping) if row else None


def renew_lease(db: Session, batch_id: uuid.UUID, worker_id: str, lease_seconds: int) -> bool:
    """Heartbeat. False means the batch is no longer this worker's (reconciled or changed)."""
    result = db.execute(
        text(
            "UPDATE public.test_batches SET heartbeat_at = clock_timestamp(), "
            "lease_expires_at = clock_timestamp() + make_interval(secs => :ls) "
            "WHERE id = :i AND worker_id = :w AND status IN ('dispatched', 'running', 'cancel_requested')"
        ),
        {"i": batch_id, "w": worker_id, "ls": lease_seconds},
    )
    return result.rowcount == 1  # type: ignore[attr-defined, no-any-return]


def dispatch_candidates(db: Session) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """(batch_id, run_id) of queued, not yet dispatched batches that may be sent now,
    oldest run first and in batch order."""
    rows = db.execute(
        text(
            "SELECT b.id, b.run_id FROM public.test_batches b "
            "JOIN public.test_runs r ON r.id = b.run_id "
            "WHERE b.status = 'queued' AND b.queue_task_id IS NULL "
            "AND r.status IN ('queued', 'dispatched', 'running') "
            "AND (b.not_before IS NULL OR b.not_before <= clock_timestamp()) "
            "ORDER BY r.created_at, b.ordinal"
        )
    ).all()
    return [(r[0], r[1]) for r in rows]


def outstanding_counts(db: Session) -> dict[uuid.UUID, int]:
    """Batches per run that occupy a concurrency slot: claimed by a worker, or sent to the
    queue and waiting for one."""
    rows = db.execute(
        text(
            "SELECT run_id, count(*) FROM public.test_batches WHERE "
            "status IN ('dispatched', 'running', 'cancel_requested') "
            "OR (status = 'queued' AND queue_task_id IS NOT NULL) GROUP BY run_id"
        )
    ).all()
    return {r[0]: int(r[1]) for r in rows}


def assign_task(db: Session, batch_id: uuid.UUID, task_id: str, lease_seconds: int) -> bool:
    result = db.execute(
        text(
            "UPDATE public.test_batches SET queue_task_id = :t, "
            "lease_expires_at = clock_timestamp() + make_interval(secs => :ls) "
            "WHERE id = :i AND status = 'queued' AND queue_task_id IS NULL"
        ),
        {"i": batch_id, "t": task_id, "ls": lease_seconds},
    )
    return result.rowcount == 1  # type: ignore[attr-defined, no-any-return]


def release_expired_dispatches(db: Session) -> list[BatchRecord]:
    """Queued batches whose message never produced a claim before the enqueue deadline:
    forget the task id so the dispatcher sends them again."""
    rows = db.execute(
        text(
            "UPDATE public.test_batches SET queue_task_id = NULL, lease_expires_at = NULL "
            "WHERE status = 'queued' AND queue_task_id IS NOT NULL "
            f"AND lease_expires_at < clock_timestamp() RETURNING {_BATCH}"
        )
    ).all()
    return [BatchRecord(**r._mapping) for r in rows]


def batches_with_expired_lease(db: Session) -> list[BatchRecord]:
    rows = db.execute(
        text(
            f"SELECT {_BATCH} FROM public.test_batches WHERE "
            "status IN ('dispatched', 'running', 'cancel_requested') "
            "AND lease_expires_at < clock_timestamp() ORDER BY created_at"
        )
    ).all()
    return [BatchRecord(**r._mapping) for r in rows]


def batches_overrunning(db: Session, grace_seconds: int) -> list[BatchRecord]:
    rows = db.execute(
        text(
            f"SELECT {_BATCH} FROM public.test_batches WHERE status = 'running' "
            "AND started_at + make_interval(secs => timeout_seconds + :g) < clock_timestamp()"
        ),
        {"g": grace_seconds},
    ).all()
    return [BatchRecord(**r._mapping) for r in rows]


def batches_cancel_overdue(db: Session, grace_seconds: int) -> list[BatchRecord]:
    rows = db.execute(
        text(
            f"SELECT {', '.join('b.' + c.strip() for c in _BATCH.split(','))} "
            "FROM public.test_batches b JOIN public.test_runs r ON r.id = b.run_id "
            "WHERE b.status = 'cancel_requested' AND r.cancel_requested_at "
            "+ make_interval(secs => :g) < clock_timestamp()"
        ),
        {"g": grace_seconds},
    ).all()
    return [BatchRecord(**r._mapping) for r in rows]


# ---- results -------------------------------------------------------------------------------


def insert_result(
    db: Session,
    *,
    run_id: uuid.UUID,
    batch_id: uuid.UUID,
    planned_test_id: uuid.UUID,
    attempt: int,
    status: str,
    summary: str | None,
    exit_code: int | None = None,
    duration_ms: int | None = None,
) -> uuid.UUID | None:
    """Idempotent on (batch, test, attempt): a duplicate delivery inserts nothing (None)."""
    row = db.execute(
        text(
            "INSERT INTO public.test_results (run_id, batch_id, planned_test_id, attempt, status, "
            "summary, exit_code, duration_ms, started_at, finished_at) VALUES "
            "(:r, :b, :t, :a, :s, :sum, :ec, :d, now(), now()) "
            "ON CONFLICT ON CONSTRAINT test_results_attempt_unique DO NOTHING RETURNING id"
        ),
        {
            "r": run_id,
            "b": batch_id,
            "t": planned_test_id,
            "a": attempt,
            "s": status,
            "sum": summary,
            "ec": exit_code,
            "d": duration_ms,
        },
    ).first()
    return uuid.UUID(str(row[0])) if row else None


def insert_evidence_artifact(
    db: Session,
    *,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    result_id: uuid.UUID,
    kind: str,
    storage_key: str,
    sha256: str,
    size_bytes: int,
    content_type: str,
    filename: str,
) -> uuid.UUID:
    """Metadata for evidence bytes already written to the artifact store."""
    row = db.execute(
        text(
            "INSERT INTO public.artifacts (project_id, run_id, result_id, kind, storage_key, "
            "sha256, size_bytes, content_type, original_filename, validation_status, "
            "redaction_status) VALUES (:p, :r, :res, :k, :key, :h, :s, :c, :f, 'not_required', "
            "'redacted') RETURNING id"
        ),
        {"p": project_id, "r": run_id, "res": result_id, "k": kind, "key": storage_key,
         "h": sha256, "s": size_bytes, "c": content_type, "f": filename},
    ).one()  # fmt: skip
    return uuid.UUID(str(row[0]))


def list_evidence(db: Session, run_id: uuid.UUID, result_id: uuid.UUID) -> list[tuple[str, str]]:
    rows = db.execute(
        text(
            "SELECT original_filename, storage_key FROM public.artifacts "
            "WHERE run_id = :r AND result_id = :res AND deleted_at IS NULL ORDER BY original_filename"
        ),
        {"r": run_id, "res": result_id},
    ).all()
    return [(r[0], r[1]) for r in rows]


def finished_test_ids(db: Session, batch_id: uuid.UUID) -> set[uuid.UUID]:
    """Tests that already have a result in any earlier attempt. A retry must not run them
    again; only a test that never started (``failed_to_start``) may be retried."""
    rows = db.execute(
        text(
            "SELECT DISTINCT planned_test_id FROM public.test_results "
            "WHERE batch_id = :b AND status <> 'failed_to_start'"
        ),
        {"b": batch_id},
    ).all()
    return {r[0] for r in rows}


def list_results(
    db: Session, run_id: uuid.UUID, *, status: str | None, limit: int
) -> list[ResultRecord]:
    rows = db.execute(
        text(
            f"SELECT {_RESULT} FROM public.test_results WHERE run_id = :r "
            "AND (CAST(:s AS text) IS NULL OR status = :s) ORDER BY created_at, id LIMIT :n"
        ),
        {"r": run_id, "s": status, "n": limit},
    ).all()
    return [ResultRecord(**r._mapping) for r in rows]


def result_status_counts(db: Session, run_id: uuid.UUID) -> dict[str, int]:
    rows = db.execute(
        text("SELECT status, count(*) FROM public.test_results WHERE run_id = :r GROUP BY status"),
        {"r": run_id},
    ).all()
    return {r[0]: int(r[1]) for r in rows}


def batch_status_counts(db: Session, run_id: uuid.UUID) -> dict[str, int]:
    rows = db.execute(
        text("SELECT status, count(*) FROM public.test_batches WHERE run_id = :r GROUP BY status"),
        {"r": run_id},
    ).all()
    return {r[0]: int(r[1]) for r in rows}


def item_count(db: Session, run_id: uuid.UUID) -> int:
    return int(
        db.execute(
            text("SELECT count(*) FROM public.test_batch_items WHERE run_id = :r"), {"r": run_id}
        ).scalar_one()
    )


# ---- events --------------------------------------------------------------------------------


def insert_event(
    db: Session,
    run_id: uuid.UUID,
    event_type: str,
    *,
    batch_id: uuid.UUID | None = None,
    from_status: str | None = None,
    to_status: str | None = None,
    actor_user_id: uuid.UUID | None = None,
    worker_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    db.execute(
        text(
            "INSERT INTO public.job_events (run_id, batch_id, event_type, from_status, to_status, "
            "actor_user_id, worker_id, detail) VALUES (:r, :b, :e, :f, :t, :a, :w, CAST(:d AS jsonb))"
        ),
        {
            "r": run_id,
            "b": batch_id,
            "e": event_type,
            "f": from_status,
            "t": to_status,
            "a": actor_user_id,
            "w": worker_id,
            "d": json.dumps(detail or {}, default=str),
        },
    )


def list_events(db: Session, run_id: uuid.UUID, *, after: int, limit: int) -> list[EventRecord]:
    rows = db.execute(
        text(
            "SELECT id, run_id, batch_id, event_type, from_status, to_status, actor_user_id, "
            "worker_id, detail, created_at FROM public.job_events "
            "WHERE run_id = :r AND id > :a ORDER BY id LIMIT :n"
        ),
        {"r": run_id, "a": after, "n": limit},
    ).all()
    return [EventRecord(**r._mapping) for r in rows]


def lock_advisory(db: Session, key: int) -> bool:
    """Transaction-scoped advisory lock; False if another dispatcher/reconciler holds it."""
    return bool(db.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": key}).scalar_one())


def unassign_task(db: Session, batch_id: uuid.UUID, task_id: str) -> bool:
    """The message could not be published: forget the task id so the next pass retries."""
    result = db.execute(
        text(
            "UPDATE public.test_batches SET queue_task_id = NULL, lease_expires_at = NULL "
            "WHERE id = :i AND status = 'queued' AND queue_task_id = :t"
        ),
        {"i": batch_id, "t": task_id},
    )
    return result.rowcount == 1  # type: ignore[attr-defined, no-any-return]
