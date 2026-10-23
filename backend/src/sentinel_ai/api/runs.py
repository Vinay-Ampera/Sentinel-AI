"""Test runs: create, status/progress, batches, results, events and cancellation (Stage 7).

Every route needs the role capability AND project access: routes with ``{project_id}`` use
the project dependency, routes addressed by run/batch id authorize from the row's own
project in the service. Break-glass grants are read-only, so they can read runs but can
neither start nor cancel one.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy.orm import Session

from sentinel_ai.api.deps import (
    get_db,
    request_context,
    require_permission,
    require_project_access,
)
from sentinel_ai.core.permissions import AccessLevel, Permission
from sentinel_ai.schemas.runs import (
    BatchOut,
    CreateRunRequest,
    EventOut,
    ResultDetailOut,
    ResultOut,
    RunOut,
)
from sentinel_ai.services import runs as service
from sentinel_ai.services.audit import RequestContext
from sentinel_ai.services.auth import Principal

router = APIRouter(tags=["test-runs"])

_VIEW = Depends(require_permission(Permission.PROJECT_VIEW))
_RUN_ROLE = Depends(require_permission(Permission.PLAN_AND_RUN))
_READ = Depends(require_project_access(AccessLevel.READ))
_RUN = Depends(require_project_access(AccessLevel.RUN))
_VIEW_PRINCIPAL = Depends(require_permission(Permission.PROJECT_VIEW))
_RUN_PRINCIPAL = Depends(require_permission(Permission.PLAN_AND_RUN))


@router.post("/projects/{project_id}/test-runs", status_code=202, dependencies=[_RUN_ROLE])
def create_run(
    project_id: uuid.UUID,
    body: CreateRunRequest,
    request: Request,
    idempotency_key: Annotated[str | None, Header(min_length=8, max_length=128)] = None,
    principal: Principal = _RUN,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> RunOut:
    run, created = service.create_run(
        db, ctx, principal.user, request.app.state.settings,
        project_id=project_id, plan_id=body.plan_id,
        timeout_seconds=body.timeout_seconds, idempotency_key=idempotency_key,
    )  # fmt: skip
    if created:  # committed by the service; hand the batches to the queue
        request.app.state.dispatch()
    view = service.get_run(db, ctx, principal.user, run.id)
    return RunOut.from_view(view)


@router.get("/projects/{project_id}/test-runs", dependencies=[_VIEW])
def list_runs(
    project_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    principal: Principal = _READ,
    db: Session = Depends(get_db),
) -> list[RunOut]:
    return [RunOut.of(r) for r in service.list_runs(db, project_id, limit)]


@router.get("/test-runs/{run_id}")
def get_run(
    run_id: uuid.UUID,
    principal: Principal = _VIEW_PRINCIPAL,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> RunOut:
    return RunOut.from_view(service.get_run(db, ctx, principal.user, run_id))


@router.post("/test-runs/{run_id}/cancel", status_code=202)
def cancel_run(
    run_id: uuid.UUID,
    principal: Principal = _RUN_PRINCIPAL,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> RunOut:
    return RunOut.from_view(service.cancel_run(db, ctx, principal.user, run_id))


@router.get("/test-runs/{run_id}/batches")
def list_batches(
    run_id: uuid.UUID,
    principal: Principal = _VIEW_PRINCIPAL,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> list[BatchOut]:
    return [BatchOut.of(b) for b in service.list_batches(db, ctx, principal.user, run_id)]


@router.get("/test-batches/{batch_id}")
def get_batch(
    batch_id: uuid.UUID,
    principal: Principal = _VIEW_PRINCIPAL,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> BatchOut:
    return BatchOut.of(service.get_batch(db, ctx, principal.user, batch_id))


@router.get("/test-runs/{run_id}/results")
def list_results(
    run_id: uuid.UUID,
    status: str | None = Query(default=None, max_length=30),
    principal: Principal = _VIEW_PRINCIPAL,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> list[ResultOut]:
    rows = service.list_results(db, ctx, principal.user, run_id, status)
    return [ResultOut.of(r) for r in rows]


@router.get("/test-runs/{run_id}/results/{result_id}")
def get_result(
    run_id: uuid.UUID,
    result_id: uuid.UUID,
    principal: Principal = _VIEW_PRINCIPAL,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> ResultDetailOut:
    detail = service.get_result_detail(db, ctx, principal.user, run_id, result_id)
    return ResultDetailOut.from_detail(detail)


_DOWNLOAD_TYPES = {"text/plain; charset=utf-8", "application/json", "application/xml"}


@router.get("/artifacts/{artifact_id}/content")
def download_evidence(
    artifact_id: uuid.UUID,
    request: Request,
    principal: Principal = _VIEW_PRINCIPAL,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    """Run evidence only (a log or report), authorized through the artifact's own project.
    Always an attachment, never sniffed or rendered by the browser."""
    record, data = service.read_evidence(
        db, ctx, principal.user, request.app.state.settings, artifact_id
    )
    media = (
        record.content_type
        if record.content_type in _DOWNLOAD_TYPES
        else "application/octet-stream"
    )
    filename = "".join(ch for ch in (record.filename or "evidence") if ch.isalnum() or ch in "._-")
    return Response(
        content=data,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{filename or "evidence"}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@router.get("/test-runs/{run_id}/events")
def list_events(
    run_id: uuid.UUID,
    after: int = Query(default=0, ge=0),
    principal: Principal = _VIEW_PRINCIPAL,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> list[EventOut]:
    return [EventOut.of(e) for e in service.list_events(db, ctx, principal.user, run_id, after)]
