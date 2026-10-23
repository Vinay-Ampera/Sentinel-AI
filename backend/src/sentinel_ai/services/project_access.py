"""Project-scoped authorization: role grants capability, project access grants scope.

Access to a project (its plans, runs, results, logs, evidence) comes only from an explicit
grant: ownership, a membership, or team access - plus one exception: a Super Admin's
temporary, read-only, audited break-glass grant. No role - Admin or Super Admin included -
reaches a project's content through its privileges; an Admin or Super Admin who works on a
project is a project user like any other and needs a grant. Unknown and inaccessible
projects are indistinguishable (404); an accessible project with insufficient level is 403.
"""

import uuid

from sqlalchemy.orm import Session

from sentinel_ai.core.errors import DomainError
from sentinel_ai.core.permissions import AccessLevel, Role, access_level_from_name
from sentinel_ai.repositories import break_glass, project_access
from sentinel_ai.repositories.identity import UserRecord
from sentinel_ai.services import audit
from sentinel_ai.services.audit import RequestContext


def resolve_explicit_access(
    db: Session, user: UserRecord, project_id: uuid.UUID
) -> AccessLevel | None:
    """Access from ownership, membership or team only. Decisions (approvals, especially
    production) use this: temporary break-glass access never counts as a grant."""
    levels = [
        level
        for name in project_access.access_grants(db, project_id, user.id)
        if (level := access_level_from_name(name)) is not None
    ]
    return max(levels, default=None)


def has_break_glass(db: Session, user: UserRecord, project_id: uuid.UUID) -> bool:
    return user.role_name == Role.SUPER_ADMIN and break_glass.has_active(db, project_id, user.id)


def resolve_access(db: Session, user: UserRecord, project_id: uuid.UUID) -> AccessLevel | None:
    """Explicit access, or READ while the caller (a Super Admin) holds an active, audited
    break-glass grant on this project. Break-glass never reaches run/manage."""
    explicit = resolve_explicit_access(db, user, project_id)
    if explicit is None and has_break_glass(db, user, project_id):
        return AccessLevel.READ
    return explicit


def note_break_glass_use(
    db: Session,
    ctx: RequestContext,
    user: UserRecord,
    project_id: uuid.UUID,
    minimum: AccessLevel,
) -> None:
    """Audit every access that exists only because of a break-glass grant."""
    if resolve_explicit_access(db, user, project_id) is None and has_break_glass(
        db, user, project_id
    ):
        audit.record(
            db,
            ctx,
            action="breakglass.access",
            outcome="success",
            actor_user_id=user.id,
            project_id=project_id,
            detail={"min_level": minimum.name.lower()},
        )


def require_project_access(
    db: Session, user: UserRecord, project_id: uuid.UUID, minimum: AccessLevel
) -> AccessLevel:
    level = resolve_access(db, user, project_id)
    if level is None:
        raise DomainError(404, "not_found", "Project not found")
    if level < minimum:
        raise DomainError(403, "forbidden", "Insufficient access to this project")
    return level


def authorize_project(
    db: Session,
    ctx: RequestContext,
    user: UserRecord,
    project_id: uuid.UUID,
    minimum: AccessLevel,
) -> AccessLevel:
    """``require_project_access`` for routes whose path has no ``project_id`` (the project
    comes from a child row such as a plan or approval)."""
    level = require_project_access(db, user, project_id, minimum)
    note_break_glass_use(db, ctx, user, project_id, minimum)
    return level
