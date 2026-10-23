"""Recovery sweep for stuck jobs (Stage 7). Run periodically and when a worker starts.

PostgreSQL is the only source of truth: the sweep never asks the broker anything. It
  1. releases batches whose queue message never produced a claim (re-dispatched later);
  2. recovers batches whose worker stopped renewing its lease (bounded re-queue, else fail);
  3. times out batches that overran their limit and cancels that never confirmed in time;
  4. times out runs past their own limit or queue wait;
  5. gives runs whose batches are all finished their final status.
Every action leaves a ``job_events`` row, so a stuck job is visible rather than silent.
Termination of a lost worker's sandbox cannot be confirmed from here; the batch says so
(Stage 8 adds sandbox cleanup by label).
"""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from sentinel_ai.core.config import Settings
from sentinel_ai.repositories import runs
from sentinel_ai.repositories.runs import BatchRecord
from sentinel_ai.services import job_state

logger = logging.getLogger(__name__)

RECONCILE_LOCK_KEY = 0x53454E54_0002


@dataclass
class ReconcileReport:
    released: int = 0
    recovered: int = 0
    failed: int = 0
    timed_out: int = 0
    cancel_unconfirmed: int = 0
    runs_timed_out: int = 0
    runs_finalized: int = 0
    containers_swept: int = 0

    def total(self) -> int:
        return sum(self.__dict__.values())


Cleanup = Callable[[uuid.UUID], bool]


def _cleanup(cleanup: Cleanup | None, batch_id: uuid.UUID) -> bool:
    """Ask the executor to remove whatever a lost or stuck worker left running. True only
    when removal is confirmed; with no cleanup hook (stub executor) nothing is confirmed."""
    if cleanup is None:
        return False
    try:
        return bool(cleanup(batch_id))
    except Exception as exc:
        logger.error("sandbox cleanup for batch %s failed (%s)", batch_id, type(exc).__name__)
        return False


def reconcile(
    factory: sessionmaker[Session],
    settings: Settings,
    cleanup: Cleanup | None = None,
    sweep: Callable[[], int] | None = None,
) -> ReconcileReport:
    report = ReconcileReport()
    with factory() as db:
        if not runs.lock_advisory(db, RECONCILE_LOCK_KEY):
            return report  # another sweep is running
        _release_unclaimed(db, report)
        _recover_lost(db, settings, report, cleanup)
        _time_out_overruns(db, settings, report, cleanup)
        _settle_unconfirmed_cancels(db, settings, report, cleanup)
        _time_out_runs(db, settings, report)
        for run_id in runs.run_ids_all_batches_terminal(db):
            if job_state.finalize_run(db, run_id) is not None:
                report.runs_finalized += 1
        db.commit()
    if sweep is not None:
        try:
            report.containers_swept = sweep()
        except Exception as exc:
            logger.error("sandbox sweep failed (%s)", type(exc).__name__)
    if report.total():
        logger.info("reconciled: %s", report)
    return report


def _release_unclaimed(db: Session, report: ReconcileReport) -> None:
    for batch in runs.release_expired_dispatches(db):
        runs.insert_event(
            db, batch.run_id, "recovered", batch_id=batch.id, from_status="queued",
            to_status="queued", detail={"reason": "enqueue_expired"},
        )  # fmt: skip
        report.released += 1


def _fresh(db: Session, batch: BatchRecord) -> BatchRecord | None:
    """Lock the run and the batch (run first, the order everyone else uses) and re-read."""
    runs.get_run(db, batch.run_id, for_update=True)
    return runs.get_batch(db, batch.id, for_update=True)


def _recover_lost(
    db: Session, settings: Settings, report: ReconcileReport, cleanup: Cleanup | None
) -> None:
    for seen in runs.batches_with_expired_lease(db):
        batch = _fresh(db, seen)
        run = runs.get_run(db, seen.run_id)
        if batch is None or run is None or batch.status not in runs.CLAIMED:
            continue
        if batch.lease_expires_at is None or batch.worker_id != seen.worker_id:
            continue
        confirmed = _cleanup(cleanup, batch.id)  # stop any sandbox the lost worker left behind
        runs.insert_event(
            db, batch.run_id, "worker_lost", batch_id=batch.id, from_status=batch.status,
            worker_id=batch.worker_id,
            detail={"attempt": batch.attempt, "sandbox_cleanup_confirmed": confirmed},
        )  # fmt: skip
        if batch.status == "cancel_requested":
            job_state.mark_unrun(db, run, batch, "not_run", "Not run: the run was cancelled.")
            job_state.batch_to(
                db, batch, "cancelled", finish=True,
                error_code="worker_lost_during_cancel",
                error_summary=(
                    "The worker was lost while cancelling; its sandbox was removed."
                    if confirmed
                    else "The worker was lost while cancelling; sandbox termination is unconfirmed."
                ),
                detail={"termination_confirmed": confirmed},
            )  # fmt: skip
            report.recovered += 1
        elif batch.attempt < batch.max_attempts and job_state.requeue_batch(
            db, batch, base_backoff=settings.job_retry_backoff_seconds,
            worker_id=batch.worker_id, reason="worker_lost",
        ):  # fmt: skip
            report.recovered += 1
        else:
            job_state.mark_unrun(db, run, batch, "not_run", "Not run: the worker was lost.")
            job_state.batch_to(
                db, batch, "failed", finish=True, error_code="worker_lost",
                error_summary="The worker stopped responding and no retries remain.",
            )  # fmt: skip
            report.failed += 1
        job_state.finalize_run(db, batch.run_id)


def _time_out_overruns(
    db: Session, settings: Settings, report: ReconcileReport, cleanup: Cleanup | None
) -> None:
    for seen in runs.batches_overrunning(db, settings.job_cancel_grace_seconds):
        batch = _fresh(db, seen)
        run = runs.get_run(db, seen.run_id)
        if batch is None or run is None or batch.status != "running":
            continue
        _cleanup(cleanup, batch.id)
        job_state.mark_unrun(db, run, batch, "not_run", "Not run: the batch timed out.")
        job_state.batch_to(
            db, batch, "timed_out", event_type="timeout", finish=True, error_code="timeout",
            error_summary="The batch exceeded its time limit and its worker did not stop it.",
        )  # fmt: skip
        job_state.finalize_run(db, batch.run_id)
        report.timed_out += 1


def _settle_unconfirmed_cancels(
    db: Session, settings: Settings, report: ReconcileReport, cleanup: Cleanup | None
) -> None:
    for seen in runs.batches_cancel_overdue(db, settings.job_cancel_grace_seconds):
        batch = _fresh(db, seen)
        run = runs.get_run(db, seen.run_id)
        if batch is None or run is None or batch.status != "cancel_requested":
            continue
        _cleanup(cleanup, batch.id)
        job_state.mark_unrun(db, run, batch, "not_run", "Not run: the run was cancelled.")
        job_state.batch_to(
            db, batch, "failed", finish=True, error_code="cancel_unconfirmed",
            error_summary="Cancellation was requested but no termination was confirmed in time.",
        )  # fmt: skip
        job_state.finalize_run(db, batch.run_id)
        report.cancel_unconfirmed += 1


def _time_out_runs(db: Session, settings: Settings, report: ReconcileReport) -> None:
    for run_id in runs.run_ids_overdue(db, settings.job_queue_wait_seconds):
        run = runs.get_run(db, run_id, for_update=True)
        if run is None or run.status not in runs.ACTIVE:
            continue
        waited = run.started_at is None
        for batch in runs.list_batches(db, run_id, for_update=True):
            if batch.status in ("queued", "blocked"):
                job_state.mark_unrun(db, run, batch, "not_run", "Not run: the run timed out.")
                job_state.batch_to(db, batch, "cancelled", finish=True,
                                   detail={"reason": "run timed out"})  # fmt: skip
            elif batch.status in runs.CLAIMED:
                job_state.mark_unrun(db, run, batch, "not_run", "Not run: the run timed out.")
                job_state.batch_to(
                    db, batch, "timed_out", event_type="timeout", finish=True,
                    error_code="run_timeout",
                    error_summary="The run exceeded its time limit.",
                )  # fmt: skip
        code = "queue_timeout" if waited else "run_timeout"
        if runs.transition_run(
            db, run_id, run.status, "timed_out", finish=True, error_code=code,
            error_summary="Waited too long to start." if waited else "The run exceeded its time limit.",
        ):  # fmt: skip
            runs.insert_event(
                db, run_id, "timeout", from_status=run.status, to_status="timed_out",
                detail={"reason": code},
            )  # fmt: skip
            report.runs_timed_out += 1
