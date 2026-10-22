"""Project-scoped authorization: role grants capability, project access grants scope.

Unknown and inaccessible projects are indistinguishable (404); an accessible project with
insufficient level is 403. Admins have no implicit global access (SECURITY_AND_SAFETY);
only Super Admin reaches every project, and that access is audited by the caller.
"""

import uuid

from sqlalchemy.orm import Session

from sentinel_ai.core.errors import DomainError
from sentinel_ai.core.permissions import AccessLevel, Role, access_level_from_name
from sentinel_ai.repositories import project_access
from sentinel_ai.repositories.identity import UserRecord


def resolve_access(db: Session, user: UserRecord, project_id: uuid.UUID) -> AccessLevel | None:
    if user.role_name == Role.SUPER_ADMIN:
        return AccessLevel.MANAGE if project_access.project_exists(db, project_id) else None
    levels = [
        level
        for name in project_access.access_grants(db, project_id, user.id)
        if (level := access_level_from_name(name)) is not None
    ]
    return max(levels, default=None)


def require_project_access(
    db: Session, user: UserRecord, project_id: uuid.UUID, minimum: AccessLevel
) -> AccessLevel:
    level = resolve_access(db, user, project_id)
    if level is None:
        raise DomainError(404, "not_found", "Project not found")
    if level < minimum:
        raise DomainError(403, "forbidden", "Insufficient access to this project")
    return level


def is_privileged_only(db: Session, user: UserRecord, project_id: uuid.UUID) -> bool:
    """True when access exists only because the caller is Super Admin (no own grant);
    such access is audited."""
    return user.role_name == Role.SUPER_ADMIN and not project_access.access_grants(
        db, project_id, user.id
    )
