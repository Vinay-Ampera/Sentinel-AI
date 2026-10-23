"""SQL for temporary break-glass grants (``public.break_glass_grants``)."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class GrantRecord:
    id: uuid.UUID
    project_id: uuid.UUID
    user_id: uuid.UUID
    justification: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    revoked_by: uuid.UUID | None
    active: bool


_COLS = (
    "id, project_id, user_id, justification, created_at, expires_at, revoked_at, revoked_by, "
    "(revoked_at IS NULL AND expires_at > now()) AS active"
)


def has_active(db: Session, project_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Database clock decides expiry, so a skewed API host cannot extend a grant."""
    return (
        db.execute(
            text(
                "SELECT 1 FROM public.break_glass_grants WHERE project_id = :p AND user_id = :u "
                "AND revoked_at IS NULL AND expires_at > now() LIMIT 1"
            ),
            {"p": project_id, "u": user_id},
        ).first()
        is not None
    )


def insert(
    db: Session, *, project_id: uuid.UUID, user_id: uuid.UUID, justification: str, minutes: int
) -> GrantRecord:
    row = db.execute(
        text(
            "INSERT INTO public.break_glass_grants "
            "(project_id, user_id, justification, expires_at) "
            "VALUES (:p, :u, :j, now() + make_interval(mins => :m)) "
            f"RETURNING {_COLS}"
        ),
        {"p": project_id, "u": user_id, "j": justification, "m": minutes},
    ).one()
    return GrantRecord(**row._mapping)


def get(db: Session, project_id: uuid.UUID, grant_id: uuid.UUID) -> GrantRecord | None:
    row = db.execute(
        text(
            f"SELECT {_COLS} FROM public.break_glass_grants WHERE id = :i AND project_id = :p "
            "FOR UPDATE"
        ),
        {"i": grant_id, "p": project_id},
    ).first()
    return GrantRecord(**row._mapping) if row else None


def list_for_project(db: Session, project_id: uuid.UUID) -> list[GrantRecord]:
    rows = db.execute(
        text(
            f"SELECT {_COLS} FROM public.break_glass_grants WHERE project_id = :p "
            "ORDER BY created_at DESC, id LIMIT 200"
        ),
        {"p": project_id},
    ).all()
    return [GrantRecord(**r._mapping) for r in rows]


def revoke(db: Session, grant_id: uuid.UUID, revoked_by: uuid.UUID) -> GrantRecord:
    row = db.execute(
        text(
            "UPDATE public.break_glass_grants SET revoked_at = now(), revoked_by = :u "
            f"WHERE id = :i RETURNING {_COLS}"
        ),
        {"i": grant_id, "u": revoked_by},
    ).one()
    return GrantRecord(**row._mapping)
