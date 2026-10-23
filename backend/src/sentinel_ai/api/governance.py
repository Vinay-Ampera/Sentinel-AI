"""Target authorizations and approval policies (Stage 6)."""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from sentinel_ai.api.deps import (
    get_db,
    request_context,
    require_permission,
    require_project_access,
)
from sentinel_ai.core.permissions import AccessLevel, Permission
from sentinel_ai.schemas.plans import (
    AuthorizationOut,
    AuthorizationRequestBody,
    EffectivePolicyOut,
    PolicyValueRequest,
)
from sentinel_ai.services import authorizations as service
from sentinel_ai.services import policy as policy_service
from sentinel_ai.services.audit import RequestContext
from sentinel_ai.services.auth import Principal

router = APIRouter(tags=["governance"])

_VIEW = [Depends(require_permission(Permission.PROJECT_VIEW))]
_SOURCES = [Depends(require_permission(Permission.SOURCE_MANAGE))]
_READ = Depends(require_project_access(AccessLevel.READ))
_MANAGE = Depends(require_project_access(AccessLevel.MANAGE))
_GLOBAL_POLICY = Depends(require_permission(Permission.POLICY_GLOBAL))


@router.post(
    "/projects/{project_id}/sources/{source_id}/authorizations",
    status_code=201,
    dependencies=_SOURCES,
)
def request_authorization(
    project_id: uuid.UUID,
    source_id: uuid.UUID,
    body: AuthorizationRequestBody,
    principal: Principal = _MANAGE,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> AuthorizationOut:
    auth = service.request_authorization(
        db,
        ctx,
        principal.user,
        project_id,
        source_id,
        environment=body.environment,
        paths=body.paths,
        methods=body.methods,
        allowed_risk=body.allowed_risk,
        valid_from=body.valid_from,
        valid_until=body.valid_until,
        justification=body.justification,
    )
    return AuthorizationOut.from_record(auth, datetime.now(UTC))


@router.get("/projects/{project_id}/authorizations", dependencies=_VIEW)
def list_authorizations(
    project_id: uuid.UUID, _: Principal = _READ, db: Session = Depends(get_db)
) -> dict[str, list[AuthorizationOut]]:
    now = datetime.now(UTC)
    return {
        "items": [
            AuthorizationOut.from_record(a, now)
            for a in service.list_authorizations(db, project_id)
        ]
    }


@router.post(
    "/projects/{project_id}/authorizations/{authorization_id}/revoke", dependencies=_SOURCES
)
def revoke_authorization(
    project_id: uuid.UUID,
    authorization_id: uuid.UUID,
    principal: Principal = _MANAGE,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> AuthorizationOut:
    auth = service.revoke_authorization(db, ctx, principal.user, project_id, authorization_id)
    return AuthorizationOut.from_record(auth, datetime.now(UTC))


# ---- policies ---------------------------------------------------------------------------


@router.get("/projects/{project_id}/policy", dependencies=_VIEW)
def effective_policy(
    project_id: uuid.UUID, _: Principal = _READ, db: Session = Depends(get_db)
) -> EffectivePolicyOut:
    return EffectivePolicyOut.from_policy(policy_service.load_effective(db, project_id))


@router.get("/admin/policies")
def global_policies(
    _: Principal = _GLOBAL_POLICY,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return {"items": policy_service.global_rows(db)}


@router.put("/admin/policies/{key}")
def set_global_policy(
    key: str,
    body: PolicyValueRequest,
    principal: Principal = _GLOBAL_POLICY,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    return policy_service.set_policy(
        db, ctx, actor_id=principal.user.id, role=principal.user.role_name,
        key=key, value=body.value, project_id=None,
    )  # fmt: skip


@router.get("/projects/{project_id}/policies", dependencies=_VIEW)
def project_policies(
    project_id: uuid.UUID, _: Principal = _MANAGE, db: Session = Depends(get_db)
) -> dict[str, Any]:
    return {
        "items": policy_service.project_rows(db, project_id),
        "effective": EffectivePolicyOut.from_policy(policy_service.load_effective(db, project_id)),
    }


@router.put("/projects/{project_id}/policies/{key}", dependencies=_VIEW)
def set_project_policy(
    project_id: uuid.UUID,
    key: str,
    body: PolicyValueRequest,
    principal: Principal = _MANAGE,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    return policy_service.set_policy(
        db, ctx, actor_id=principal.user.id, role=principal.user.role_name,
        key=key, value=body.value, project_id=project_id,
    )  # fmt: skip
