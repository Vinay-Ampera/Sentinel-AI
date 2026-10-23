"""Celery tasks: thin wrappers around the services (Stage 7)."""

import logging
import os
import socket
import uuid
from dataclasses import dataclass
from functools import lru_cache

from celery import Task, shared_task
from sqlalchemy.orm import Session, sessionmaker

from sentinel_ai.core.config import Settings, get_settings
from sentinel_ai.db.engine import create_db_engine, create_session_factory
from sentinel_ai.execution.interface import Executor
from sentinel_ai.execution.stub import create_executor
from sentinel_ai.jobs.celery_app import DISPATCH, RECONCILE, RUN_BATCH, CeleryEnqueuer
from sentinel_ai.services import dispatcher, reconciler, worker_runtime

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Runtime:
    settings: Settings
    factory: sessionmaker[Session]
    executor: Executor
    enqueue: dispatcher.Enqueue
    worker_id: str


@lru_cache
def runtime() -> Runtime:
    settings = get_settings()
    return Runtime(
        settings=settings,
        factory=create_session_factory(create_db_engine(settings)),
        executor=create_executor(settings.job_executor),
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
    total = reconciler.reconcile(rt.factory, rt.settings).total()
    dispatcher.dispatch_pending(rt.factory, rt.settings, rt.enqueue)
    return total


@shared_task(name=DISPATCH)  # type: ignore[untyped-decorator]
def dispatch_pending_jobs() -> int:
    rt = runtime()
    return dispatcher.dispatch_pending(rt.factory, rt.settings, rt.enqueue)
