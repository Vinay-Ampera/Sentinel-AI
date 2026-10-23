"""Findings: list, detail, review status and verification (Stage 10).

Reading needs the view capability and project read access (break-glass included, audited).
Changing anything needs the triage capability and project ``run`` access, which a read-only
break-glass grant never has. Nothing here can create a finding: only a completed scan can.
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from sentinel_ai.api.deps import (
    get_db,
    request_context,
    require_permission,
    require_project_access,
)
from sentinel_ai.core.permissions import AccessLevel, Permission
from sentinel_ai.schemas.findings import (
    FindingDetailOut,
    FindingGroupOut,
    FindingOut,
    StatusRequest,
    VerificationRequest,
)
from sentinel_ai.services import findings as service
from sentinel_ai.services.audit import RequestContext
from sentinel_ai.services.auth import Principal

router = APIRouter(tags=["findings"])

_VIEW = Depends(require_permission(Permission.PROJECT_VIEW))
_TRIAGE = Depends(require_permission(Permission.EVIDENCE_AND_TRIAGE))
_READ = Depends(require_project_access(AccessLevel.READ))
_STATUSES = "^(new|triaged|in_progress|fixed|verified_fixed|accepted_risk|false_positive|reopened)$"
_SEVERITIES = "^(info|low|medium|high|critical)$"


@router.get("/projects/{project_id}/findings", dependencies=[_VIEW])
def list_findings(
    project_id: uuid.UUID,
    status: str | None = Query(default=None, pattern=_STATUSES),
    severity: str | None = Query(default=None, pattern=_SEVERITIES),
    limit: int = Query(default=100, ge=1, le=500),
    principal: Principal = _READ,
    db: Session = Depends(get_db),
) -> list[FindingOut]:
    return [
        FindingOut.of(f) for f in service.list_findings(db, project_id, status, severity, limit)
    ]


@router.get("/projects/{project_id}/finding-groups", dependencies=[_VIEW])
def list_finding_groups(
    project_id: uuid.UUID,
    limit: int = Query(default=100, ge=1, le=500),
    principal: Principal = _READ,
    db: Session = Depends(get_db),
) -> list[FindingGroupOut]:
    """Duplicate groups across scanners. Members are listed in full, each with its own tool."""
    return [FindingGroupOut.of(g) for g in service.list_groups(db, project_id, limit)]


@router.get("/findings/{finding_id}")
def get_finding(
    finding_id: uuid.UUID,
    principal: Principal = _VIEW,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> FindingDetailOut:
    return FindingDetailOut.from_detail(service.get_detail(db, ctx, principal.user, finding_id))


@router.post("/findings/{finding_id}/status")
def change_status(
    finding_id: uuid.UUID,
    body: StatusRequest,
    principal: Principal = _TRIAGE,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> FindingDetailOut:
    detail = service.change_status(db, ctx, principal.user, finding_id, body.status, body.note)
    return FindingDetailOut.from_detail(detail)


@router.post("/findings/{finding_id}/verification")
def set_verification(
    finding_id: uuid.UUID,
    body: VerificationRequest,
    principal: Principal = _TRIAGE,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> FindingDetailOut:
    detail = service.set_verification(db, ctx, principal.user, finding_id, body.state, body.note)
    return FindingDetailOut.from_detail(detail)
