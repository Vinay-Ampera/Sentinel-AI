import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sentinel_ai.api import (
    admin,
    auth,
    break_glass,
    findings,
    governance,
    health,
    plans,
    projects,
    runs,
)
from sentinel_ai.core.config import Settings, get_settings
from sentinel_ai.core.errors import install_error_handlers
from sentinel_ai.core.logging import configure_logging
from sentinel_ai.core.middleware import install_middleware
from sentinel_ai.core.ratelimit import RateLimiter
from sentinel_ai.db.engine import create_db_engine, create_session_factory
from sentinel_ai.jobs.celery_app import CeleryEnqueuer
from sentinel_ai.services import dispatcher
from sentinel_ai.services.artifact_store import ArtifactStore

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Application factory. Settings are validated here, so a missing or invalid
    configuration stops startup with a clear, value-free message.

    Run with: uvicorn sentinel_ai.main:create_app --factory
    """
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_db_engine(settings)  # lazy: no connection is opened here
        app.state.settings = settings
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        if not hasattr(app.state, "enqueue"):  # tests may install their own
            app.state.enqueue = CeleryEnqueuer(settings)

        def dispatch() -> int:
            """Hand queued batches to the broker. The run is already committed, so a failure
            here must not fail the request: the periodic dispatcher picks the batch up."""
            try:
                return dispatcher.dispatch_pending(
                    app.state.session_factory, settings, app.state.enqueue
                )
            except Exception as exc:
                logger.warning(
                    "dispatch failed (%s); the periodic dispatcher will retry", type(exc).__name__
                )
                return 0

        app.state.dispatch = dispatch
        try:
            purged = ArtifactStore(settings.artifact_root()).purge_stale_temp()
        except OSError:
            purged = 0
            logger.warning("could not purge stale upload temp files")
        if purged:
            logger.info("purged %d stale upload temp files", purged)
        logger.info("startup complete: %s", settings.safe_summary())
        yield
        engine.dispose()

    app = FastAPI(title="Sentinel AI", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token", "Idempotency-Key", "X-Request-ID"],
    )
    install_middleware(app)
    install_error_handlers(app)
    app.state.settings = settings
    app.state.plan_limiter = RateLimiter(plans.PLANS_PER_MINUTE)
    app.state.login_limiter = RateLimiter(settings.login_ip_max_attempts_per_minute)
    app.include_router(health.router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(admin.router, prefix="/api/v1")
    app.include_router(projects.router, prefix="/api/v1")
    app.include_router(plans.router, prefix="/api/v1")
    app.include_router(governance.router, prefix="/api/v1")
    app.include_router(break_glass.router, prefix="/api/v1")
    app.include_router(runs.router, prefix="/api/v1")
    app.include_router(findings.router, prefix="/api/v1")
    return app
