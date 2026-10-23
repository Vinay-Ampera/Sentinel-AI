"""Worker / beat entry point (Stage 7). Run from ``backend/``:

    poetry run celery -A sentinel_ai.jobs.worker worker -Q sentinel-jobs --concurrency 2 -l INFO
    poetry run celery -A sentinel_ai.jobs.worker beat -l INFO

The worker is a separate process from the API and never serves HTTP. It reads the same
settings (DATABASE_URL, REDIS_URL, ...) from the environment or ``backend/.env``.
"""

import logging
from typing import Any

from celery.signals import worker_ready

from sentinel_ai.core.config import get_settings
from sentinel_ai.core.logging import configure_logging
from sentinel_ai.jobs import tasks
from sentinel_ai.jobs.celery_app import make_celery

_settings = get_settings()
configure_logging(_settings.log_level)
app = make_celery(_settings)
__all__ = ["app", "tasks"]  # importing ``tasks`` registers the task names


@worker_ready.connect  # type: ignore[untyped-decorator]
def _reconcile_on_start(**_: Any) -> None:
    """After a restart, recover anything whose lease has already expired."""
    try:
        tasks.reconcile_jobs.delay()
    except Exception as exc:
        logging.getLogger(__name__).warning("startup reconcile not queued (%s)", type(exc).__name__)
