"""Test plans and the approval inbox (Stage 6).

Every route needs the role capability AND project access (checked by the dependency for
routes with ``{project_id}``, or by the service from the plan/approval's own project for
routes addressed by plan/approval id). Approval authority is decided by policy code, not by
the route.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from sentinel_ai.api.deps import (
    current_principal,
    get_db,
    request_context,
    require_permission,
    require_project_access,
)
from sentinel_ai.core.errors import DomainError
from sentinel_ai.core.permissions import AccessLevel, Permission
from sentinel_ai.schemas.plans import (
    ApprovalOut,
    CreatePlanRequest,
    DecisionRequest,
    PlanOut,
    PlanSummaryOut,
    UpdatePlanRequest,
)
from sentinel_ai.services import approvals as approvals_service
from sentinel_ai.services import plans as service
from sentinel_ai.services.audit import RequestContext
from sentinel_ai.services.auth import Principal

router = APIRouter(tags=["test-plans"])

_VIEW = [Depends(require_permission(Permission.PROJECT_VIEW))]
_PLAN_ROLE = [Depends(require_permission(Permission.PLAN_AND_RUN))]
_READ = Depends(require_project_access(AccessLevel.READ))
_RUN = Depends(require_project_access(AccessLevel.RUN))
PLANS_PER_MINUTE = 30


@router.post("/projects/{project_id}/test-plans", status_code=201, dependencies=_PLAN_ROLE)
def create_plan(
    project_id: uuid.UUID,
    body: CreatePlanRequest,
    request: Request,
    principal: Principal = _RUN,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> PlanOut:
    if not request.app.state.plan_limiter.allow(str(principal.user.id)):
        raise DomainError(429, "rate_limited", "Too many plans created; try again shortly")
    detail = service.create_plan(
        db,
        ctx,
        principal.user,
        project_id,
        mode=body.mode,
        snapshot_id=body.snapshot_id,
        prompt=body.prompt,
        tests=[t.to_input() for t in body.tests],
    )
    return PlanOut.from_detail(detail)


@router.get("/projects/{project_id}/test-plans", dependencies=_VIEW)
def list_plans(
    project_id: uuid.UUID,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    _: Principal = _READ,
    db: Session = Depends(get_db),
) -> dict[str, list[PlanSummaryOut]]:
    return {
        "items": [PlanSummaryOut.from_record(p) for p in service.list_plans(db, project_id, limit)]
    }


@router.get("/test-plans/{plan_id}", dependencies=_VIEW)
def get_plan(
    plan_id: uuid.UUID,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> PlanOut:
    detail = service.get_plan(db, ctx, principal.user, plan_id, AccessLevel.READ)
    can_approve = approvals_service.viewer_can_approve(db, principal.user, detail.approval)
    return PlanOut.from_detail(detail, can_approve)


@router.patch("/test-plans/{plan_id}", dependencies=_PLAN_ROLE)
def update_plan(
    plan_id: uuid.UUID,
    body: UpdatePlanRequest,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> PlanOut:
    detail = service.edit_plan(
        db,
        ctx,
        principal.user,
        plan_id,
        summary=body.summary,
        remove_test_ids=body.remove_test_ids,
        add_tests=[t.to_input() for t in body.add_tests],
    )
    return PlanOut.from_detail(detail)


@router.post("/test-plans/{plan_id}/submit", dependencies=_PLAN_ROLE)
def submit_plan(
    plan_id: uuid.UUID,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> PlanOut:
    return PlanOut.from_detail(service.submit_plan(db, ctx, principal.user, plan_id))


@router.get("/approvals")
def list_approvals(
    status: str = "pending",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, list[ApprovalOut]]:
    rows = approvals_service.list_approvals(db, ctx, principal.user, status, limit)
    return {"items": [ApprovalOut.from_record(a) for a in rows]}


@router.post("/approvals/{approval_id}/decision")
def decide_approval(
    approval_id: uuid.UUID,
    body: DecisionRequest,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> ApprovalOut:
    decided = approvals_service.decide(
        db, ctx, principal.user, approval_id, decision=body.decision, reason=body.reason
    )
    return ApprovalOut.from_record(decided)
