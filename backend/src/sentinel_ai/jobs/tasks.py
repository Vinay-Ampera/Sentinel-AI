"""Celery tasks: thin wrappers around the services (Stage 7)."""

import logging
import os
import socket
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

from celery import Task, shared_task
from sqlalchemy.orm import Session, sessionmaker

from sentinel_ai.core.config import Settings, get_settings
from sentinel_ai.db.engine import create_db_engine, create_session_factory
from sentinel_ai.execution.factory import create_executor
from sentinel_ai.execution.interface import Executor
from sentinel_ai.jobs.celery_app import (
    DISPATCH,
    EVALUATE_ALERTS,
    PURGE_EVENTS,
    RECONCILE,
    RUN_BATCH,
    CeleryEnqueuer,
)
from sentinel_ai.services import alerts, dispatcher, event_retention, reconciler, worker_runtime

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Runtime:
    settings: Settings
    factory: sessionmaker[Session]
    executor: Executor
    enqueue: dispatcher.Enqueue
    worker_id: str
    cleanup: Callable[[uuid.UUID], bool] | None = None
    sweep: Callable[[], int] | None = None


@lru_cache
def runtime() -> Runtime:
    settings = get_settings()
    executor = create_executor(settings)
    return Runtime(
        settings=settings,
        factory=create_session_factory(create_db_engine(settings)),
        executor=executor,
        cleanup=getattr(executor, "terminate", None) if settings.job_executor == "docker" else None,
        sweep=getattr(executor, "sweep", None) if settings.job_executor == "docker" else None,
        enqueue=CeleryEnqueuer(settings),
        worker_id=f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}",
    )


@shared_task(name=RUN_BATCH, bind=True, acks_late=True, reject_on_worker_lost=True)  # type: ignore[untyped-decorator]
def run_batch(self: Task, batch_id: str) -> str:
    rt = runtime()
    outcome = worker_runtime.process_batch(
        rt.factory,
        rt.settings,
        rt.executor,
        uuid.UUID(batch_id),
        str(self.request.id),
        rt.worker_id,
    )
    dispatcher.dispatch_pending(rt.factory, rt.settings, rt.enqueue)  # next batch, if any
    return outcome


@shared_task(name=RECONCILE)  # type: ignore[untyped-decorator]
def reconcile_jobs() -> int:
    rt = runtime()
    total = reconciler.reconcile(
        rt.factory, rt.settings, cleanup=rt.cleanup, sweep=rt.sweep
    ).total()
    dispatcher.dispatch_pending(rt.factory, rt.settings, rt.enqueue)
    return total


@shared_task(name=DISPATCH)  # type: ignore[untyped-decorator]
def dispatch_pending_jobs() -> int:
    rt = runtime()
    return dispatcher.dispatch_pending(rt.factory, rt.settings, rt.enqueue)


@shared_task(name=EVALUATE_ALERTS)  # type: ignore[untyped-decorator]
def evaluate_alert_rules() -> int:
    """Time-driven alert rules (silence after activity, model cost and runaway rules) for the
    projects that need them. Returns the number of projects evaluated."""
    rt = runtime()
    done, failed = alerts.evaluate_scheduled(rt.factory, rt.settings)
    if failed:
        logger.warning("alert evaluation: %d project(s) failed", failed)
    return done


@shared_task(name=PURGE_EVENTS)  # type: ignore[untyped-decorator]
def purge_expired_events() -> int:
    """Delete expired observability data (ADR-0011 retention). Only scheduled when
    EVENT_PURGE_ENABLED is true; returns the number of rows deleted."""
    rt = runtime()
    counts = event_retention.purge(rt.factory, rt.settings, dry_run=False)
    total = sum(counts.values())
    logger.info("purged expired events: %s", counts)
    return total
