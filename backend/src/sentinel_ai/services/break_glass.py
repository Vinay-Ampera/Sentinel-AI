"""Temporary Super Admin break-glass access to one project (incident response).

Deliberately narrow: READ only (never run, manage or decide approvals), at most four hours,
a written justification, no extension (grant a new one), revocable at once by the grantee or
by anyone with explicit manage access to the project. Everything is audited: the grant, every
request served only because of it (``breakglass.access``) and the revocation. Expiry is
judged by the database clock. Project managers can see the grants on their project.
"""

import uuid

from sqlalchemy.orm import Session

from sentinel_ai.core.errors import DomainError
from sentinel_ai.core.permissions import AccessLevel, Permission, has_permission
from sentinel_ai.repositories import break_glass, project_access
from sentinel_ai.repositories.break_glass import GrantRecord
from sentinel_ai.repositories.identity import UserRecord
from sentinel_ai.services import audit
from sentinel_ai.services import project_access as access_service
from sentinel_ai.services.audit import RequestContext

MIN_MINUTES = 5
DEFAULT_MINUTES = 60
MAX_MINUTES = 240
MIN_JUSTIFICATION = 20


def grant(
    db: Session,
    ctx: RequestContext,
    user: UserRecord,
    project_id: uuid.UUID,
    *,
    justification: str,
    minutes: int,
) -> GrantRecord:
    if not has_permission(user.role_name, Permission.BREAK_GLASS):
        raise DomainError(403, "forbidden", "Only a Super Admin can use break-glass access")
    text = " ".join(justification.split())
    if len(text) < MIN_JUSTIFICATION:
        raise DomainError(
            422,
            "validation_failed",
            f"A justification of at least {MIN_JUSTIFICATION} characters is required",
        )
    if not MIN_MINUTES <= minutes <= MAX_MINUTES:
        raise DomainError(422, "validation_failed", f"minutes must be {MIN_MINUTES}-{MAX_MINUTES}")
    if not project_access.project_exists(db, project_id):
        raise DomainError(404, "not_found", "Project not found")
    if break_glass.has_active(db, project_id, user.id):
        raise DomainError(409, "conflict", "You already hold an active break-glass grant here")
    record = break_glass.insert(
        db, project_id=project_id, user_id=user.id, justification=text, minutes=minutes
    )
    audit.record(
        db,
        ctx,
        action="breakglass.grant",
        outcome="success",
        actor_user_id=user.id,
        project_id=project_id,
        target_type="break_glass_grant",
        target_id=str(record.id),
        detail={
            "justification": text,
            "minutes": minutes,
            "expires_at": record.expires_at.isoformat(),
            "access": "read",
            "explicit_access_held": access_service.resolve_explicit_access(db, user, project_id)
            is not None,
        },
    )
    return record


def list_grants(db: Session, project_id: uuid.UUID) -> list[GrantRecord]:
    return break_glass.list_for_project(db, project_id)


def revoke(
    db: Session,
    ctx: RequestContext,
    user: UserRecord,
    project_id: uuid.UUID,
    grant_id: uuid.UUID,
) -> GrantRecord:
    record = break_glass.get(db, project_id, grant_id)  # scoped by project, row-locked
    if record is None:
        raise DomainError(404, "not_found", "Grant not found")
    explicit = access_service.resolve_explicit_access(db, user, project_id)
    if record.user_id != user.id and (explicit is None or explicit < AccessLevel.MANAGE):
        raise DomainError(404, "not_found", "Grant not found")  # no existence leak
    if not record.active:
        raise DomainError(409, "conflict", "The grant has already ended")
    revoked = break_glass.revoke(db, grant_id, user.id)
    audit.record(
        db,
        ctx,
        action="breakglass.revoke",
        outcome="success",
        actor_user_id=user.id,
        project_id=project_id,
        target_type="break_glass_grant",
        target_id=str(grant_id),
        detail={"grantee": str(record.user_id), "by_grantee": record.user_id == user.id},
    )
    return revoked
