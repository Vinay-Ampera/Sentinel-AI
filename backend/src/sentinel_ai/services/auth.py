"""Login, session validation, logout, and password change (ADR-0002)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from sentinel_ai.core import security
from sentinel_ai.core.config import Settings
from sentinel_ai.core.errors import DomainError
from sentinel_ai.repositories import identity
from sentinel_ai.repositories.identity import SessionRecord, UserRecord
from sentinel_ai.services import audit
from sentinel_ai.services.audit import RequestContext

INVALID_CREDENTIALS = DomainError(401, "invalid_credentials", "Invalid email or password")


@dataclass(frozen=True)
class LoginResult:
    user: UserRecord
    session_token: str
    csrf_token: str


@dataclass(frozen=True)
class Principal:
    """The authenticated caller, resolved from a valid server-side session."""

    user: UserRecord
    session_id: uuid.UUID
    csrf_token_hash: bytes


def login(
    db: Session, settings: Settings, ctx: RequestContext, email: str, password: str
) -> LoginResult:
    """Verify credentials and open a new session. Every failure mode returns the same
    error; the reason is recorded in the audit log only."""
    pepper = settings.pepper()
    user = identity.get_user_by_email(db, security.normalize_email(email), for_update=True)

    if user is None:
        security.verify_password(security.DUMMY_PASSWORD_HASH, password)  # equalise timing
        audit.record(db, ctx, action="auth.login", outcome="failure", detail={"reason": "unknown"})
        db.commit()
        raise INVALID_CREDENTIALS

    now = datetime.now(UTC)
    locked = user.locked_until is not None and user.locked_until > now
    # Always verify, even for locked/inactive accounts, so timing does not reveal state.
    password_ok = security.verify_password(user.password_hash, password)

    if locked or not user.is_active or not password_ok:
        reason = "locked" if locked else "inactive" if not user.is_active else "bad_password"
        if reason == "bad_password":
            _register_failure(db, settings, ctx, user, now)
        audit.record(
            db,
            ctx,
            action="auth.login",
            outcome="failure",
            actor_user_id=user.id,
            detail={"reason": reason},
        )
        db.commit()
        raise INVALID_CREDENTIALS

    if security.password_needs_rehash(user.password_hash):
        identity.replace_password_hash_only(db, user.id, security.hash_password(password))
    identity.record_successful_login(db, user.id)

    token = security.new_session_token()
    csrf = security.csrf_token_for(pepper, token)
    session_id = identity.create_session(
        db,
        user_id=user.id,
        token_hash=security.session_token_hash(pepper, token),
        csrf_hash=security.csrf_token_hash(pepper, csrf),
        idle_minutes=settings.session_idle_minutes,
        absolute_hours=settings.session_absolute_hours,
        ip_address=ctx.ip_address,
        user_agent=ctx.user_agent,
    )
    audit.record(
        db,
        ctx,
        action="auth.login",
        outcome="success",
        actor_user_id=user.id,
        target_type="session",
        target_id=str(session_id),
    )
    db.commit()
    return LoginResult(user=user, session_token=token, csrf_token=csrf)


def _register_failure(
    db: Session, settings: Settings, ctx: RequestContext, user: UserRecord, now: datetime
) -> None:
    will_lock = user.failed_login_count + 1 >= settings.login_max_failures
    identity.record_failed_login(
        db,
        user.id,
        lock_until=now + timedelta(minutes=settings.login_lockout_minutes) if will_lock else None,
        reset_count=will_lock,
    )
    if will_lock:
        audit.record(
            db, ctx, action="auth.lockout", outcome="success", actor_user_id=user.id,
            detail={"minutes": settings.login_lockout_minutes},
        )  # fmt: skip


def authenticate_session(db: Session, settings: Settings, session_token: str) -> Principal | None:
    """Resolve a raw cookie token to a principal, sliding the idle expiry. None if the
    session is unknown, revoked, expired, or its user is deactivated."""
    token_hash = security.session_token_hash(settings.pepper(), session_token)
    active = identity.find_active_session(db, token_hash)
    if active is None:
        return None
    identity.touch_session(db, active.session_id, settings.session_idle_minutes)
    return Principal(active.user, active.session_id, active.csrf_token_hash)


def logout(db: Session, ctx: RequestContext, principal: Principal) -> None:
    identity.revoke_session(db, principal.session_id, principal.user.id, "logout")
    audit.record(
        db, ctx, action="auth.logout", outcome="success", actor_user_id=principal.user.id,
        target_type="session", target_id=str(principal.session_id),
    )  # fmt: skip


def change_password(
    db: Session, ctx: RequestContext, principal: Principal, current: str, new: str
) -> int:
    """Change the caller's password and revoke their other sessions. Returns the number
    of sessions revoked."""
    user = identity.get_user(db, principal.user.id, for_update=True)
    if user is None or not security.verify_password(user.password_hash, current):
        audit.record(
            db, ctx, action="auth.password_change", outcome="failure",
            actor_user_id=principal.user.id, detail={"reason": "bad_current_password"},
        )  # fmt: skip
        db.commit()
        raise DomainError(400, "invalid_current_password", "Current password is incorrect")
    problems = security.password_policy_violations(new, email=user.email)
    if problems or security.verify_password(user.password_hash, new):
        raise DomainError(
            422,
            "weak_password",
            "New password does not meet the password policy",
            [{"field": "new", "issue": p} for p in problems]
            or [{"field": "new", "issue": "must differ from the current password"}],
        )
    identity.set_password_hash(db, user.id, security.hash_password(new))
    revoked = identity.revoke_user_sessions(
        db, user.id, "password_changed", except_session=principal.session_id
    )
    audit.record(
        db, ctx, action="auth.password_change", outcome="success", actor_user_id=user.id,
        detail={"sessions_revoked": revoked},
    )  # fmt: skip
    return revoked


def list_sessions(db: Session, principal: Principal) -> list[SessionRecord]:
    return identity.list_user_sessions(db, principal.user.id)


def revoke_own_session(
    db: Session, ctx: RequestContext, principal: Principal, session_id: uuid.UUID
) -> None:
    """Sessions of other users are indistinguishable from nonexistent ones (404)."""
    if not identity.revoke_session(db, session_id, principal.user.id, "user_revoked"):
        raise DomainError(404, "not_found", "Session not found")
    audit.record(
        db, ctx, action="auth.session_revoke", outcome="success", actor_user_id=principal.user.id,
        target_type="session", target_id=str(session_id),
    )  # fmt: skip
