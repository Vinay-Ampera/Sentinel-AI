"""All SQL for accounts, sessions, and audit events (schema: migrations 0001/0002)."""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class UserRecord:
    id: uuid.UUID
    email: str
    display_name: str
    password_hash: str
    role_name: str
    is_active: bool
    failed_login_count: int
    locked_until: datetime | None
    last_login_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class SessionRecord:
    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    ip_address: str | None
    user_agent: str | None


_USER_COLS = (
    "id, email, display_name, password_hash, role_name, is_active, failed_login_count, "
    "locked_until, last_login_at, created_at"
)


def _user(row: Any) -> UserRecord:
    return UserRecord(**row._mapping)


def get_user_by_email(db: Session, email: str, *, for_update: bool = False) -> UserRecord | None:
    sql = f"SELECT {_USER_COLS} FROM app_user.users WHERE email = :email"
    row = db.execute(text(sql + (" FOR UPDATE" if for_update else "")), {"email": email}).first()
    return _user(row) if row else None


def get_user(db: Session, user_id: uuid.UUID, *, for_update: bool = False) -> UserRecord | None:
    sql = f"SELECT {_USER_COLS} FROM app_user.users WHERE id = :id"
    row = db.execute(text(sql + (" FOR UPDATE" if for_update else "")), {"id": user_id}).first()
    return _user(row) if row else None


def list_users(db: Session, query: str | None, limit: int) -> list[UserRecord]:
    where = "WHERE email ILIKE :pat OR display_name ILIKE :pat " if query else ""
    rows = db.execute(
        text(
            f"SELECT {_USER_COLS} FROM app_user.users {where}ORDER BY created_at, id LIMIT :limit"
        ),
        {"pat": f"%{_escape_like(query)}%" if query else None, "limit": limit}
        if query
        else {"limit": limit},
    ).all()
    return [_user(r) for r in rows]


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def create_user(
    db: Session, *, email: str, display_name: str, password_hash: str, role_name: str
) -> UserRecord:
    row = db.execute(
        text(
            "INSERT INTO app_user.users (email, display_name, password_hash, role_name) "
            f"VALUES (:email, :name, :ph, :role) RETURNING {_USER_COLS}"
        ),
        {"email": email, "name": display_name, "ph": password_hash, "role": role_name},
    ).one()
    return _user(row)


def update_user_fields(db: Session, user_id: uuid.UUID, fields: dict[str, Any]) -> None:
    allowed = {"display_name", "role_name", "is_active", "deactivated_at"}
    if not fields or not set(fields) <= allowed:
        raise ValueError("unsupported user fields")
    assignments = ", ".join(f"{name} = :{name}" for name in fields)
    db.execute(
        text(f"UPDATE app_user.users SET {assignments} WHERE id = :id"), {**fields, "id": user_id}
    )


def count_active_super_admins(db: Session) -> int:
    """Call after ``lock_super_admin_rows`` in the same transaction."""
    row = db.execute(
        text("SELECT count(*) FROM app_user.users WHERE role_name = 'super_admin' AND is_active")
    ).one()
    return int(row[0])


def lock_super_admin_rows(db: Session) -> None:
    """Serialise concurrent changes that could remove the last Super Admin."""
    db.execute(text("SELECT id FROM app_user.users WHERE role_name = 'super_admin' FOR UPDATE"))


def record_failed_login(
    db: Session, user_id: uuid.UUID, *, lock_until: datetime | None, reset_count: bool
) -> None:
    db.execute(
        text(
            "UPDATE app_user.users SET "
            "failed_login_count = CASE WHEN :reset THEN 0 ELSE failed_login_count + 1 END, "
            "locked_until = COALESCE(:lock_until, locked_until) WHERE id = :id"
        ),
        {"id": user_id, "lock_until": lock_until, "reset": reset_count},
    )


def record_successful_login(db: Session, user_id: uuid.UUID) -> None:
    db.execute(
        text(
            "UPDATE app_user.users SET failed_login_count = 0, locked_until = NULL, "
            "last_login_at = now() WHERE id = :id"
        ),
        {"id": user_id},
    )


def set_password_hash(db: Session, user_id: uuid.UUID, password_hash: str) -> None:
    db.execute(
        text(
            "UPDATE app_user.users SET password_hash = :ph, password_changed_at = now() "
            "WHERE id = :id"
        ),
        {"id": user_id, "ph": password_hash},
    )


def replace_password_hash_only(db: Session, user_id: uuid.UUID, password_hash: str) -> None:
    """Transparent rehash on login; the password itself did not change."""
    db.execute(
        text("UPDATE app_user.users SET password_hash = :ph WHERE id = :id"),
        {"id": user_id, "ph": password_hash},
    )


# ---- sessions ------------------------------------------------------------


def create_session(
    db: Session,
    *,
    user_id: uuid.UUID,
    token_hash: bytes,
    csrf_hash: bytes,
    idle_minutes: int,
    absolute_hours: int,
    ip_address: str | None,
    user_agent: str | None,
) -> uuid.UUID:
    row = db.execute(
        text(
            "INSERT INTO app_user.sessions (user_id, token_hash, csrf_token_hash, "
            "idle_expires_at, absolute_expires_at, ip_address, user_agent) VALUES "
            "(:uid, :th, :ch, now() + make_interval(mins => :idle), "
            "now() + make_interval(hours => :abs), CAST(:ip AS inet), :ua) RETURNING id"
        ),
        {
            "uid": user_id,
            "th": token_hash,
            "ch": csrf_hash,
            "idle": idle_minutes,
            "abs": absolute_hours,
            "ip": ip_address,
            "ua": user_agent[:512] if user_agent else None,
        },
    ).one()
    return uuid.UUID(str(row[0]))


@dataclass(frozen=True)
class ActiveSession:
    session_id: uuid.UUID
    csrf_token_hash: bytes
    user: UserRecord


def find_active_session(db: Session, token_hash: bytes) -> ActiveSession | None:
    """Session that is unrevoked, inside both expiries, with an active user."""
    row = db.execute(
        text(
            "SELECT s.id AS session_id, s.csrf_token_hash, "
            + ", ".join(f"u.{c.strip()}" for c in _USER_COLS.split(","))
            + " FROM app_user.sessions s JOIN app_user.users u ON u.id = s.user_id "
            "WHERE s.token_hash = :th AND s.revoked_at IS NULL "
            "AND s.idle_expires_at > now() AND s.absolute_expires_at > now() AND u.is_active"
        ),
        {"th": token_hash},
    ).first()
    if row is None:
        return None
    data = dict(row._mapping)
    session_id, csrf = data.pop("session_id"), data.pop("csrf_token_hash")
    return ActiveSession(uuid.UUID(str(session_id)), bytes(csrf), UserRecord(**data))


def touch_session(db: Session, session_id: uuid.UUID, idle_minutes: int) -> None:
    db.execute(
        text(
            "UPDATE app_user.sessions SET last_seen_at = now(), "
            "idle_expires_at = LEAST(now() + make_interval(mins => :idle), absolute_expires_at) "
            "WHERE id = :id"
        ),
        {"id": session_id, "idle": idle_minutes},
    )


def list_user_sessions(db: Session, user_id: uuid.UUID) -> list[SessionRecord]:
    rows = db.execute(
        text(
            "SELECT id, user_id, created_at, last_seen_at, idle_expires_at, absolute_expires_at, "
            "host(ip_address) AS ip_address, user_agent FROM app_user.sessions "
            "WHERE user_id = :uid AND revoked_at IS NULL AND idle_expires_at > now() "
            "AND absolute_expires_at > now() ORDER BY created_at DESC"
        ),
        {"uid": user_id},
    ).all()
    return [SessionRecord(**r._mapping) for r in rows]


def revoke_session(db: Session, session_id: uuid.UUID, user_id: uuid.UUID, reason: str) -> bool:
    """Revoke one session owned by ``user_id``; False if none matched."""
    result = db.execute(
        text(
            "UPDATE app_user.sessions SET revoked_at = now(), revoked_reason = :r "
            "WHERE id = :id AND user_id = :uid AND revoked_at IS NULL"
        ),
        {"id": session_id, "uid": user_id, "r": reason},
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


def revoke_user_sessions(
    db: Session, user_id: uuid.UUID, reason: str, *, except_session: uuid.UUID | None = None
) -> int:
    result = db.execute(
        text(
            "UPDATE app_user.sessions SET revoked_at = now(), revoked_reason = :r "
            "WHERE user_id = :uid AND revoked_at IS NULL "
            "AND (CAST(:keep AS uuid) IS NULL OR id <> CAST(:keep AS uuid))"
        ),
        {"uid": user_id, "r": reason, "keep": except_session},
    )
    return int(result.rowcount)  # type: ignore[attr-defined]


# ---- audit ---------------------------------------------------------------


def insert_audit_event(
    db: Session,
    *,
    actor_type: str,
    actor_user_id: uuid.UUID | None,
    action: str,
    outcome: str,
    target_type: str | None,
    target_id: str | None,
    project_id: uuid.UUID | None,
    request_id: str | None,
    ip_address: str | None,
    detail: dict[str, Any],
) -> None:
    db.execute(
        text(
            "INSERT INTO public.audit_events (actor_type, actor_user_id, action, target_type, "
            "target_id, project_id, outcome, request_id, ip_address, detail) VALUES "
            "(:at, :au, :action, :tt, :tid, :pid, :outcome, :rid, CAST(:ip AS inet), "
            "CAST(:detail AS jsonb))"
        ),
        {
            "at": actor_type,
            "au": actor_user_id,
            "action": action,
            "tt": target_type,
            "tid": target_id,
            "pid": project_id,
            "outcome": outcome,
            "rid": request_id,
            "ip": ip_address,
            "detail": json.dumps(detail),
        },
    )
