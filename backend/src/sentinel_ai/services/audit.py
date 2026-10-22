"""Audit trail writer. ``public.audit_events`` is append-only (DB trigger)."""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from sentinel_ai.repositories import identity

_SENSITIVE_KEYS = ("password", "token", "secret", "hash", "csrf", "cookie", "authorization")


@dataclass(frozen=True)
class RequestContext:
    """Who/where a request came from, for audit rows. The IP is the direct peer address;
    X-Forwarded-For is deliberately not trusted until a trusted-proxy setting exists."""

    request_id: str | None
    ip_address: str | None
    user_agent: str | None


def _redact(detail: dict[str, Any]) -> dict[str, Any]:
    return {
        key: ("[redacted]" if any(s in key.lower() for s in _SENSITIVE_KEYS) else value)
        for key, value in detail.items()
    }


def record(
    db: Session,
    ctx: RequestContext,
    *,
    action: str,
    outcome: str,
    actor_user_id: uuid.UUID | None = None,
    actor_type: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    project_id: uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Add an audit row in the caller's transaction (caller commits)."""
    identity.insert_audit_event(
        db,
        actor_type=actor_type or ("user" if actor_user_id else "system"),
        actor_user_id=actor_user_id,
        action=action,
        outcome=outcome,
        target_type=target_type,
        target_id=target_id,
        project_id=project_id,
        request_id=ctx.request_id,
        ip_address=ctx.ip_address,
        detail=_redact(detail or {}),
    )
