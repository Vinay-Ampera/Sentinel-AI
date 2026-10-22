import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sentinel_ai.api import health
from sentinel_ai.core.config import Settings, get_settings
from sentinel_ai.core.errors import install_error_handlers
from sentinel_ai.core.logging import configure_logging
from sentinel_ai.core.middleware import install_middleware
from sentinel_ai.db.engine import create_db_engine, create_session_factory

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
    app.include_router(health.router, prefix="/api/v1")
    return app
