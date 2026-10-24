import tempfile
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from sentinel_ai.api.deps import (
    current_principal,
    get_db,
    get_settings_dep,
    request_context,
    require_permission,
    require_project_access,
)
from sentinel_ai.core.config import Settings
from sentinel_ai.core.errors import DomainError
from sentinel_ai.core.permissions import AccessLevel, Permission
from sentinel_ai.schemas.projects import (
    AnalysisRequest,
    CreateProjectRequest,
    MemberOut,
    MemberRequest,
    ProjectOut,
    SnapshotOut,
    SourceOut,
    UpdateProjectRequest,
    UrlSourceRequest,
)
from sentinel_ai.services import project_access
from sentinel_ai.services import projects as service
from sentinel_ai.services.artifact_store import ArtifactStore
from sentinel_ai.services.audit import RequestContext
from sentinel_ai.services.auth import Principal

router = APIRouter(tags=["projects"])

# Role capability and project scope must both allow each action (SECURITY_AND_SAFETY).
_CREATE = Depends(require_permission(Permission.PROJECT_CREATE))
_VIEW = [Depends(require_permission(Permission.PROJECT_VIEW))]
_READ = Depends(require_project_access(AccessLevel.READ))
_RUN = Depends(require_project_access(AccessLevel.RUN))
_MANAGE = Depends(require_project_access(AccessLevel.MANAGE))
_SOURCES = [Depends(require_permission(Permission.SOURCE_MANAGE))]
_ANALYZE = [Depends(require_permission(Permission.PROJECT_ANALYZE))]
_MEMBERS = [Depends(require_permission(Permission.MEMBERS_MANAGE))]
_ZIP_TYPES = {"application/zip", "application/x-zip-compressed", "application/octet-stream"}


@router.post("/projects", status_code=201)
def create_project(
    body: CreateProjectRequest,
    principal: Principal = _CREATE,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> ProjectOut:
    project = service.create_project(
        db,
        ctx,
        principal.user,
        name=body.name,
        description=body.description,
        application_type=body.application_type,
    )
    return ProjectOut.from_record(project, AccessLevel.MANAGE)


@router.get("/projects", dependencies=_VIEW)
def list_projects(
    include_archived: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, list[ProjectOut]]:
    rows = service.list_projects(
        db, ctx, principal.user, include_archived=include_archived, limit=limit
    )
    return {"items": [ProjectOut.from_record(p, level) for p, level in rows]}


@router.get("/projects/{project_id}", dependencies=_VIEW)
def get_project(
    project_id: uuid.UUID, principal: Principal = _READ, db: Session = Depends(get_db)
) -> ProjectOut:
    # The caller's own access level (a read-only break-glass grant shows as "read"): the UI uses
    # it only to show or hide controls; the server still decides every action.
    level = project_access.resolve_access(db, principal.user, project_id)
    return ProjectOut.from_record(service.get_project(db, project_id), level)


@router.patch("/projects/{project_id}", dependencies=_VIEW)
def update_project(
    project_id: uuid.UUID,
    body: UpdateProjectRequest,
    principal: Principal = _MANAGE,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> ProjectOut:
    project = service.update_project(
        db, ctx, principal.user, project_id, name=body.name, description=body.description
    )
    return ProjectOut.from_record(project, AccessLevel.MANAGE)  # this route needs manage


@router.post("/projects/{project_id}/archive", dependencies=_VIEW)
def archive_project(
    project_id: uuid.UUID,
    principal: Principal = _MANAGE,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> ProjectOut:
    archived = service.archive_project(db, ctx, principal.user, project_id)
    return ProjectOut.from_record(archived, AccessLevel.MANAGE)  # this route needs manage


# ---- members --------------------------------------------------------------------------


@router.get("/projects/{project_id}/members", dependencies=_VIEW)
def list_members(
    project_id: uuid.UUID, _: Principal = _MANAGE, db: Session = Depends(get_db)
) -> dict[str, list[MemberOut]]:
    return {"items": [MemberOut.from_record(m) for m in service.list_members(db, project_id)]}


@router.put("/projects/{project_id}/members/{user_id}", dependencies=_MEMBERS, status_code=204)
def set_member(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    body: MemberRequest,
    principal: Principal = _MANAGE,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    service.set_member(db, ctx, principal.user, project_id, user_id, body.access_level)
    return Response(status_code=204)


@router.delete("/projects/{project_id}/members/{user_id}", dependencies=_MEMBERS, status_code=204)
def remove_member(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    principal: Principal = _MANAGE,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    service.remove_member(db, ctx, principal.user, project_id, user_id)
    return Response(status_code=204)


# ---- sources --------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/sources/zip",
    dependencies=_SOURCES,
    status_code=201,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
async def upload_zip_source(
    request: Request,
    project_id: uuid.UUID,
    name: Annotated[str, Query(min_length=1, max_length=200)],
    principal: Principal = _MANAGE,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    ctx: RequestContext = Depends(request_context),
) -> SourceOut:
    """Register a ZIP as the project's source. The body is the raw ZIP (Content-Type
    application/zip), streamed with a hard size limit. The archive is validated, never
    extracted, and never executed."""
    if any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise DomainError(422, "validation_failed", "name contains control characters")
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type not in _ZIP_TYPES:
        raise DomainError(415, "unsupported_media_type", "Send the ZIP as application/zip")
    limit = settings.upload_max_mb * 1024 * 1024
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isdigit() or int(declared) > limit):
        raise DomainError(413, "payload_too_large", "Upload exceeds the size limit")

    store = ArtifactStore(settings.artifact_root())
    handle = tempfile.NamedTemporaryFile(dir=store.temp_dir(), prefix="upload-", delete=False)
    temp_path = Path(handle.name)
    try:
        received = 0
        with handle:
            async for chunk in request.stream():
                received += len(chunk)
                if received > limit:
                    raise DomainError(413, "payload_too_large", "Upload exceeds the size limit")
                handle.write(chunk)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    source = await run_in_threadpool(
        service.register_zip_source,
        db,
        ctx,
        settings,
        principal.user,
        project_id,
        name=name.strip(),
        temp_path=temp_path,
    )
    return SourceOut.from_record(source)


@router.post("/projects/{project_id}/sources", dependencies=_SOURCES, status_code=201)
def register_url_source(
    project_id: uuid.UUID,
    body: UrlSourceRequest,
    principal: Principal = _MANAGE,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> SourceOut:
    """Register a Git repository, localhost URL, or dev/staging URL descriptor. Nothing is
    contacted; production targets are refused."""
    source = service.register_url_source(
        db, ctx, principal.user, project_id, source_type=body.source_type, name=body.name,
        git_url=body.git_url, git_ref=body.git_ref, target_url=body.target_url,
        environment=body.environment,
    )  # fmt: skip
    return SourceOut.from_record(source)


@router.get("/projects/{project_id}/sources", dependencies=_VIEW)
def list_sources(
    project_id: uuid.UUID, _: Principal = _READ, db: Session = Depends(get_db)
) -> dict[str, list[SourceOut]]:
    return {"items": [SourceOut.from_record(s) for s in service.list_sources(db, project_id)]}


@router.delete("/projects/{project_id}/sources/{source_id}", dependencies=_SOURCES, status_code=204)
def deactivate_source(
    project_id: uuid.UUID,
    source_id: uuid.UUID,
    principal: Principal = _MANAGE,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    service.deactivate_source(db, ctx, principal.user, project_id, source_id)
    return Response(status_code=204)


# ---- analyses -------------------------------------------------------------------------


@router.post("/projects/{project_id}/analyses", dependencies=_ANALYZE, status_code=201)
def run_analysis(
    project_id: uuid.UUID,
    body: AnalysisRequest,
    principal: Principal = _RUN,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    ctx: RequestContext = Depends(request_context),
) -> SnapshotOut:
    snapshot = service.run_analysis(db, ctx, settings, principal.user, project_id, body.source_id)
    return SnapshotOut.from_record(snapshot)


@router.get("/projects/{project_id}/analyses", dependencies=_VIEW)
def list_analyses(
    project_id: uuid.UUID,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    _: Principal = _READ,
    db: Session = Depends(get_db),
) -> dict[str, list[SnapshotOut]]:
    return {
        "items": [SnapshotOut.from_record(s) for s in service.list_snapshots(db, project_id, limit)]
    }


@router.get("/analyses/{analysis_id}", dependencies=_VIEW)
def get_analysis(
    analysis_id: uuid.UUID,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> SnapshotOut:
    snapshot = service.get_snapshot(db, ctx, principal.user, analysis_id)
    if snapshot is None:  # unknown and inaccessible look the same
        raise DomainError(404, "not_found", "Analysis not found")
    return SnapshotOut.from_record(snapshot)
