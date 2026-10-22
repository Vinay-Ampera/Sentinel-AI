"""User administration and first Super Admin bootstrap (docs/SECURITY_AND_SAFETY.md matrix)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sentinel_ai.core import security
from sentinel_ai.core.errors import DomainError
from sentinel_ai.core.permissions import Permission, Role, has_permission, role_from_name
from sentinel_ai.repositories import identity
from sentinel_ai.repositories.identity import UserRecord
from sentinel_ai.services import audit
from sentinel_ai.services.audit import RequestContext


def _weak_password(problems: list[str]) -> DomainError:
    return DomainError(
        422,
        "weak_password",
        "Password does not meet the password policy",
        [{"field": "password", "issue": p} for p in problems],
    )


def _can_manage(actor: UserRecord, target_role: str) -> bool:
    """Admins manage Developers only; managing Admin/Super Admin accounts needs Super Admin."""
    needed = (
        Permission.USER_MANAGE_DEVELOPERS
        if target_role == Role.DEVELOPER
        else Permission.USER_MANAGE_PRIVILEGED
    )
    return has_permission(actor.role_name, needed)


def _deny(db: Session, ctx: RequestContext, actor: UserRecord, action: str, target: str) -> None:
    audit.record(
        db, ctx, action=action, outcome="denied", actor_user_id=actor.id,
        target_type="user", target_id=target,
    )  # fmt: skip
    db.commit()
    raise DomainError(403, "forbidden", "You do not have permission to perform this action")


def create_user(
    db: Session,
    ctx: RequestContext,
    actor: UserRecord,
    *,
    email: str,
    display_name: str,
    role: str,
    password: str,
) -> UserRecord:
    email = security.normalize_email(email)
    if role_from_name(role) is None:
        raise DomainError(422, "validation_failed", "Unknown role")
    if not _can_manage(actor, role):
        _deny(db, ctx, actor, "user.create", "new")
    if not security.is_valid_email(email):
        raise DomainError(422, "validation_failed", "Invalid email address")
    problems = security.password_policy_violations(password, email=email)
    if problems:
        raise _weak_password(problems)
    try:
        user = identity.create_user(
            db,
            email=email,
            display_name=display_name.strip(),
            password_hash=security.hash_password(password),
            role_name=role,
        )
    except IntegrityError:
        db.rollback()
        raise DomainError(409, "conflict", "A user with this email already exists") from None
    audit.record(
        db, ctx, action="user.create", outcome="success", actor_user_id=actor.id,
        target_type="user", target_id=str(user.id), detail={"role": role},
    )  # fmt: skip
    return user


def update_user(
    db: Session,
    ctx: RequestContext,
    actor: UserRecord,
    user_id: uuid.UUID,
    *,
    display_name: str | None = None,
    is_active: bool | None = None,
    role: str | None = None,
) -> UserRecord:
    """Apply a partial update. Rules enforced here, not in the route:

    * Admins act on Developers only and cannot change roles; Super Admins act on anyone.
    * No one changes their own role or active flag (prevents self-lockout/self-escalation).
    * The last active Super Admin cannot be demoted or deactivated.
    * Role change or deactivation revokes the target's sessions.
    """
    if role is not None and role_from_name(role) is None:
        raise DomainError(422, "validation_failed", "Unknown role")
    lock_needed = role is not None or is_active is False
    if lock_needed:
        identity.lock_super_admin_rows(db)
    target = identity.get_user(db, user_id, for_update=True)
    if target is None:
        raise DomainError(404, "not_found", "User not found")

    changes_privilege = role is not None and role != target.role_name
    if not _can_manage(actor, target.role_name) or (
        changes_privilege and not has_permission(actor.role_name, Permission.USER_MANAGE_PRIVILEGED)
    ):
        _deny(db, ctx, actor, "user.update", str(user_id))
    if target.id == actor.id and (changes_privilege or is_active is False):
        _deny(db, ctx, actor, "user.update", str(user_id))

    fields: dict[str, object] = {}
    if display_name is not None:
        fields["display_name"] = display_name.strip()
    if changes_privilege and role is not None:
        fields["role_name"] = role
    if is_active is not None and is_active != target.is_active:
        fields["is_active"] = is_active
        fields["deactivated_at"] = None if is_active else datetime.now(UTC)

    removes_super_admin = target.role_name == Role.SUPER_ADMIN and (
        (changes_privilege and role != Role.SUPER_ADMIN) or is_active is False
    )
    if removes_super_admin and target.is_active and identity.count_active_super_admins(db) <= 1:
        raise DomainError(409, "last_super_admin", "The last Super Admin cannot be removed")

    if fields:
        identity.update_user_fields(db, user_id, fields)
    revoked = 0
    if changes_privilege or is_active is False:
        revoked = identity.revoke_user_sessions(db, user_id, "account_changed")
    if fields:
        audit.record(
            db, ctx, action="user.update", outcome="success", actor_user_id=actor.id,
            target_type="user", target_id=str(user_id),
            detail={"fields": sorted(k for k in fields if k != "deactivated_at"),
                    "sessions_revoked": revoked},
        )  # fmt: skip
    updated = identity.get_user(db, user_id)
    assert updated is not None
    return updated


def bootstrap_super_admin(
    db: Session, ctx: RequestContext, *, email: str, display_name: str, password: str
) -> UserRecord:
    """Create the first (or an additional) Super Admin from the operator's local command.
    Not reachable over HTTP."""
    email = security.normalize_email(email)
    if not security.is_valid_email(email):
        raise ValueError("invalid email address")
    problems = security.password_policy_violations(password, email=email)
    if problems:
        raise ValueError("password " + "; ".join(problems))
    if identity.get_user_by_email(db, email) is not None:
        raise ValueError("a user with this email already exists")
    user = identity.create_user(
        db,
        email=email,
        display_name=display_name.strip(),
        password_hash=security.hash_password(password),
        role_name=Role.SUPER_ADMIN,
    )
    audit.record(
        db, ctx, action="user.bootstrap_super_admin", outcome="success", actor_type="system",
        target_type="user", target_id=str(user.id),
    )  # fmt: skip
    return user
