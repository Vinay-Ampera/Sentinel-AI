"""Celery application factory (Stage 7). Redis is the broker only: no result backend, and
task messages carry nothing but identifiers. PostgreSQL decides every status."""

import uuid
from typing import Any

from celery import Celery

from sentinel_ai.core.config import Settings

RUN_BATCH = "sentinel_ai.run_batch"
RECONCILE = "sentinel_ai.reconcile"
DISPATCH = "sentinel_ai.dispatch_pending"
EVALUATE_ALERTS = "sentinel_ai.evaluate_alerts"
PURGE_EVENTS = "sentinel_ai.purge_events"


def make_celery(settings: Settings, *, publisher: bool = False) -> Celery:
    """``publisher=True`` is the API side: short timeouts so a broker outage fails fast
    (the batch stays safe in PostgreSQL and is dispatched again later)."""
    app = Celery("sentinel_ai", broker=settings.redis_url.get_secret_value())
    transport: dict[str, Any] = {
        # An unacknowledged message is redelivered after this; redelivery is harmless
        # because only the latest dispatch of a queued batch can be claimed.
        "visibility_timeout": settings.job_batch_timeout_seconds + 600,
    }
    if publisher:
        transport["socket_connect_timeout"] = settings.redis_timeout_seconds
        transport["socket_timeout"] = settings.redis_timeout_seconds
    schedule: dict[str, Any] = {
        "reconcile": {
            "task": RECONCILE,
            "schedule": float(settings.job_reconcile_interval_seconds),
        },
        "dispatch": {
            "task": DISPATCH,
            "schedule": float(settings.job_reconcile_interval_seconds),
        },
    }
    if settings.alert_evaluation_enabled:
        schedule["evaluate_alerts"] = {
            "task": EVALUATE_ALERTS,
            "schedule": float(settings.alert_evaluation_interval_seconds),
        }
    if settings.event_purge_enabled:  # deletes expired observability data: opt-in
        schedule["purge_events"] = {
            "task": PURGE_EVENTS,
            "schedule": float(settings.event_purge_interval_seconds),
        }
    app.conf.update(
        task_default_queue=settings.job_queue_name,
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        task_ignore_result=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        broker_connection_retry_on_startup=True,
        broker_transport_options=transport,
        task_soft_time_limit=settings.job_batch_timeout_seconds + settings.job_cancel_grace_seconds,
        task_time_limit=settings.job_batch_timeout_seconds + 2 * settings.job_cancel_grace_seconds,
        timezone="UTC",
        enable_utc=True,
        beat_schedule=schedule,
    )
    return app


class CeleryEnqueuer:
    """Publishes one batch message. The Celery app is created on first use, so building the
    API never touches the broker."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._app: Celery | None = None

    def __call__(self, batch_id: uuid.UUID, task_id: str) -> None:
        if self._app is None:
            self._app = make_celery(self._settings, publisher=True)
        self._app.send_task(
            RUN_BATCH,
            args=[str(batch_id)],
            task_id=task_id,
            queue=self._settings.job_queue_name,
            retry=True,
            retry_policy={"max_retries": 1, "interval_start": 0, "interval_step": 0.2},
        )
