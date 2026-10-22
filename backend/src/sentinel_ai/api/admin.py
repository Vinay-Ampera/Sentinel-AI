import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from sentinel_ai.api.deps import get_db, request_context, require_permission
from sentinel_ai.core.permissions import Permission
from sentinel_ai.repositories import identity
from sentinel_ai.schemas.identity import AdminUserOut, CreateUserRequest, UpdateUserRequest
from sentinel_ai.services import users
from sentinel_ai.services.audit import RequestContext
from sentinel_ai.services.auth import Principal

router = APIRouter(tags=["users"])

_CAN_LIST_USERS = Depends(require_permission(Permission.USER_LIST))
# Admins reach the service (to create/update Developers); the service denies privileged targets.
_CAN_MANAGE_USERS = Depends(require_permission(Permission.USER_MANAGE_DEVELOPERS))


@router.get("/users")
def list_users(
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    _: Principal = _CAN_LIST_USERS,
    db: Session = Depends(get_db),
) -> dict[str, list[AdminUserOut]]:
    return {"items": [AdminUserOut.from_record(u) for u in identity.list_users(db, q, limit)]}


@router.post("/admin/users", status_code=201)
def create_user(
    body: CreateUserRequest,
    principal: Principal = _CAN_MANAGE_USERS,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> AdminUserOut:
    user = users.create_user(
        db, ctx, principal.user,
        email=body.email, display_name=body.display_name, role=body.role,
        password=body.password.get_secret_value(),
    )  # fmt: skip
    return AdminUserOut.from_record(user)


@router.patch("/admin/users/{user_id}")
def update_user(
    user_id: uuid.UUID,
    body: UpdateUserRequest,
    principal: Principal = _CAN_MANAGE_USERS,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> AdminUserOut:
    user = users.update_user(
        db, ctx, principal.user, user_id,
        display_name=body.display_name, is_active=body.is_active, role=body.role,
    )  # fmt: skip
    return AdminUserOut.from_record(user)
