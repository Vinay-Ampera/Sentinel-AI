from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from sentinel_ai.core import health as probes

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
@router.get("/live")
def live() -> dict[str, str]:
    """Liveness: the process is up. Touches no dependency and exposes no configuration."""
    return {"status": "ok"}


@router.get("/ready")
def ready(request: Request) -> JSONResponse:
    """Readiness: database reachable and migrated. Redis is reported but not yet required
    (the job queue is used from Stage 7). Responses contain status words only."""
    state = request.app.state
    if not hasattr(state, "engine"):
        return JSONResponse({"status": "not_ready", "checks": {}}, status_code=503)
    checks: dict[str, Any] = {"database": probes.check_database(state.engine)}
    checks["migrations"] = (
        probes.check_migrations(state.engine) if checks["database"] == "ok" else "unknown"
    )
    checks["redis"] = probes.check_redis(state.settings)
    is_ready = checks["database"] == "ok" and checks["migrations"] == "ok"
    return JSONResponse(
        {"status": "ready" if is_ready else "not_ready", "checks": checks},
        status_code=200 if is_ready else 503,
    )
