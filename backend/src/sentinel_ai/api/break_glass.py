"""Break-glass access (Super Admin, temporary, read-only, audited)."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from sentinel_ai.api.deps import (
    current_principal,
    get_db,
    request_context,
    require_permission,
    require_project_access,
)
from sentinel_ai.core.permissions import AccessLevel, Permission
from sentinel_ai.repositories.break_glass import GrantRecord
from sentinel_ai.services import break_glass as service
from sentinel_ai.services.audit import RequestContext
from sentinel_ai.services.auth import Principal

router = APIRouter(tags=["break-glass"])
_MANAGE = Depends(require_project_access(AccessLevel.MANAGE))


class BreakGlassRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    justification: str = Field(min_length=1, max_length=2000)
    minutes: int = Field(default=service.DEFAULT_MINUTES, ge=1, le=1000)


class BreakGlassOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    user_id: uuid.UUID
    justification: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    revoked_by: uuid.UUID | None
    active: bool
    access: str = "read"

    @classmethod
    def from_record(cls, g: GrantRecord) -> "BreakGlassOut":
        return cls(**g.__dict__)


@router.post(
    "/projects/{project_id}/break-glass",
    status_code=201,
    dependencies=[Depends(require_permission(Permission.BREAK_GLASS))],
)
def grant_break_glass(
    project_id: uuid.UUID,
    body: BreakGlassRequest,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> BreakGlassOut:
    record = service.grant(
        db,
        ctx,
        principal.user,
        project_id,
        justification=body.justification,
        minutes=body.minutes,
    )
    return BreakGlassOut.from_record(record)


@router.get("/projects/{project_id}/break-glass")
def list_break_glass(
    project_id: uuid.UUID,
    _: Principal = _MANAGE,
    db: Session = Depends(get_db),
) -> dict[str, list[BreakGlassOut]]:
    """Project managers see who has had emergency access, why, and until when."""
    return {"items": [BreakGlassOut.from_record(g) for g in service.list_grants(db, project_id)]}


@router.post("/projects/{project_id}/break-glass/{grant_id}/revoke")
def revoke_break_glass(
    project_id: uuid.UUID,
    grant_id: uuid.UUID,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> BreakGlassOut:
    return BreakGlassOut.from_record(service.revoke(db, ctx, principal.user, project_id, grant_id))
