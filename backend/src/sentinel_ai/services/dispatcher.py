"""Hands queued batches to the broker within the concurrency limits (Stage 7).

The decision is made and committed in PostgreSQL first (a fresh ``queue_task_id`` marks the
batch as sent), then the message is published. A lost or failed publish is therefore never a
lost batch: the task id is released at once on a publish error, or by the reconciler after
the enqueue deadline. A worker claims a batch only with the latest task id, so older or
duplicate messages do nothing.
"""

import logging
import uuid
from collections.abc import Callable

from sqlalchemy.orm import Session, sessionmaker

from sentinel_ai.core.config import Settings
from sentinel_ai.repositories import runs

logger = logging.getLogger(__name__)

Enqueue = Callable[[uuid.UUID, str], None]
DISPATCH_LOCK_KEY = 0x53454E54_0001  # advisory lock id: serialises dispatch passes
ENQUEUE_LEASE_FACTOR = 5  # a sent message gets this many leases to be claimed


def dispatch_pending(factory: sessionmaker[Session], settings: Settings, enqueue: Enqueue) -> int:
    """Send every batch that fits under the per-run and global limits. Returns how many."""
    picked: list[tuple[uuid.UUID, str]] = []
    with factory() as db:
        if not runs.lock_advisory(db, DISPATCH_LOCK_KEY):
            return 0
        outstanding = runs.outstanding_counts(db)
        total = sum(outstanding.values())
        for batch_id, run_id in runs.dispatch_candidates(db):
            if total >= settings.job_max_concurrent_batches:
                break
            if outstanding.get(run_id, 0) >= settings.job_max_concurrent_batches_per_run:
                continue
            task_id = uuid.uuid4().hex
            if runs.assign_task(
                db, batch_id, task_id, settings.job_lease_seconds * ENQUEUE_LEASE_FACTOR
            ):
                picked.append((batch_id, task_id))
                outstanding[run_id] = outstanding.get(run_id, 0) + 1
                total += 1
        db.commit()

    sent = 0
    for batch_id, task_id in picked:
        try:
            enqueue(batch_id, task_id)
            sent += 1
        except Exception as exc:  # broker down, etc.; the batch stays safe in PostgreSQL
            logger.warning("could not enqueue batch %s (%s)", batch_id, type(exc).__name__)
            with factory() as db:
                runs.unassign_task(db, batch_id, task_id)
                db.commit()
    return sent
