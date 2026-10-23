"""All SQL for test plans, planned tests, approvals, and target authorizations.

Child lookups that arrive with a ``project_id`` always filter by it, so an id alone never
reaches another project's rows. Functions that take only an id (``get_plan``,
``get_approval``) return the owning ``project_id`` so the caller can authorize access before
using the row.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class PlanRecord:
    id: uuid.UUID
    project_id: uuid.UUID
    snapshot_id: uuid.UUID | None
    version: int
    plan_mode: str
    prompt: str | None
    status: str
    risk_level: str
    summary: str | None
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    content_sha256: str | None
    policy_snapshot: dict[str, Any] | None
    submitted_by: uuid.UUID | None
    submitted_at: datetime | None


@dataclass(frozen=True)
class PlannedTestRecord:
    id: uuid.UUID
    plan_id: uuid.UUID
    ordinal: int
    name: str
    category: str
    tool: str
    origin: str
    definition: dict[str, Any]
    script_artifact_id: uuid.UUID | None
    risk_level: str
    requires_approval: bool
    rationale: str | None
    status: str


@dataclass(frozen=True)
class ApprovalRecord:
    id: uuid.UUID
    plan_id: uuid.UUID | None
    authorization_id: uuid.UUID | None
    project_id: uuid.UUID
    risk_level: str
    decision: str
    requested_by: uuid.UUID
    decided_by: uuid.UUID | None
    reason: str | None
    created_at: datetime
    decided_at: datetime | None


@dataclass(frozen=True)
class AuthorizationRecord:
    id: uuid.UUID
    project_id: uuid.UUID
    source_id: uuid.UUID
    environment: str
    scope: dict[str, Any]
    allowed_risk: list[str]
    status: str
    requested_by: uuid.UUID
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    decision_note: str | None
    justification: str | None
    valid_from: datetime | None
    valid_until: datetime | None
    created_at: datetime


_PLAN = (
    "id, project_id, snapshot_id, version, plan_mode, prompt, status, risk_level, summary, "
    "created_by, created_at, updated_at, content_sha256, policy_snapshot, submitted_by, "
    "submitted_at"
)
_TEST = (
    "id, plan_id, ordinal, name, category, tool, origin, definition, script_artifact_id, "
    "risk_level, requires_approval, rationale, status"
)
_AUTH = (
    "id, project_id, source_id, environment, scope, allowed_risk, status, requested_by, "
    "decided_by, decided_at, decision_note, justification, valid_from, valid_until, created_at"
)
_APPROVAL_SELECT = (
    "SELECT a.id, a.plan_id, a.authorization_id, "
    "COALESCE(p.project_id, t.project_id) AS project_id, a.risk_level, a.decision, "
    "a.requested_by, a.decided_by, a.reason, a.created_at, a.decided_at "
    "FROM public.approvals a "
    "LEFT JOIN public.test_plans p ON p.id = a.plan_id "
    "LEFT JOIN public.target_authorizations t ON t.id = a.authorization_id "
)


def _plan(row: Any) -> PlanRecord:
    data = dict(row._mapping)
    if data["content_sha256"]:
        data["content_sha256"] = data["content_sha256"].strip()
    return PlanRecord(**data)


# ---- plans ----------------------------------------------------------------------------


def next_version(db: Session, project_id: uuid.UUID) -> int:
    row = db.execute(
        text("SELECT COALESCE(MAX(version), 0) + 1 FROM public.test_plans WHERE project_id = :p"),
        {"p": project_id},
    ).one()
    return int(row[0])


def insert_plan(
    db: Session,
    *,
    project_id: uuid.UUID,
    snapshot_id: uuid.UUID | None,
    version: int,
    plan_mode: str,
    prompt: str | None,
    risk_level: str,
    summary: str | None,
    created_by: uuid.UUID,
) -> PlanRecord:
    row = db.execute(
        text(
            "INSERT INTO public.test_plans (project_id, snapshot_id, version, plan_mode, prompt, "
            "risk_level, summary, created_by) VALUES (:p, :s, :v, :m, :pr, :r, :su, :c) "
            f"RETURNING {_PLAN}"
        ),
        {
            "p": project_id,
            "s": snapshot_id,
            "v": version,
            "m": plan_mode,
            "pr": prompt,
            "r": risk_level,
            "su": summary,
            "c": created_by,
        },
    ).one()
    return _plan(row)


def get_plan(db: Session, plan_id: uuid.UUID, *, for_update: bool = False) -> PlanRecord | None:
    sql = f"SELECT {_PLAN} FROM public.test_plans WHERE id = :i" + (
        " FOR UPDATE" if for_update else ""
    )
    row = db.execute(text(sql), {"i": plan_id}).first()
    return _plan(row) if row else None


def list_plans(db: Session, project_id: uuid.UUID, limit: int) -> list[PlanRecord]:
    rows = db.execute(
        text(
            f"SELECT {_PLAN} FROM public.test_plans WHERE project_id = :p "
            "ORDER BY version DESC LIMIT :l"
        ),
        {"p": project_id, "l": limit},
    ).all()
    return [_plan(r) for r in rows]


def update_draft(
    db: Session, plan_id: uuid.UUID, *, summary: str | None, risk_level: str
) -> PlanRecord:
    row = db.execute(
        text(
            "UPDATE public.test_plans SET summary = :s, risk_level = :r "
            f"WHERE id = :i RETURNING {_PLAN}"
        ),
        {"i": plan_id, "s": summary, "r": risk_level},
    ).one()
    return _plan(row)


def freeze_plan(
    db: Session,
    plan_id: uuid.UUID,
    *,
    status: str,
    risk_level: str,
    content_sha256: str,
    policy_snapshot: dict[str, Any],
    submitted_by: uuid.UUID,
) -> PlanRecord:
    row = db.execute(
        text(
            "UPDATE public.test_plans SET status = :st, risk_level = :r, content_sha256 = :h, "
            "policy_snapshot = CAST(:ps AS jsonb), submitted_by = :u, submitted_at = now() "
            f"WHERE id = :i RETURNING {_PLAN}"
        ),
        {
            "i": plan_id,
            "st": status,
            "r": risk_level,
            "h": content_sha256,
            "ps": json.dumps(policy_snapshot),
            "u": submitted_by,
        },
    ).one()
    return _plan(row)


def set_plan_status(db: Session, plan_id: uuid.UUID, status: str) -> PlanRecord:
    row = db.execute(
        text(f"UPDATE public.test_plans SET status = :st WHERE id = :i RETURNING {_PLAN}"),
        {"i": plan_id, "st": status},
    ).one()
    return _plan(row)


# ---- planned tests -----------------------------------------------------------------------


def insert_test(
    db: Session,
    *,
    plan_id: uuid.UUID,
    ordinal: int,
    name: str,
    category: str,
    tool: str,
    origin: str,
    definition: dict[str, Any],
    script_artifact_id: uuid.UUID | None,
    risk_level: str,
    requires_approval: bool,
    rationale: str,
    status: str,
) -> PlannedTestRecord:
    row = db.execute(
        text(
            "INSERT INTO public.planned_tests (plan_id, ordinal, name, category, tool, origin, "
            "definition, script_artifact_id, risk_level, requires_approval, rationale, status) "
            "VALUES (:p, :o, :n, :c, :t, :or, CAST(:d AS jsonb), :s, :r, :a, :ra, :st) "
            f"RETURNING {_TEST}"
        ),
        {
            "p": plan_id,
            "o": ordinal,
            "n": name,
            "c": category,
            "t": tool,
            "or": origin,
            "d": json.dumps(definition),
            "s": script_artifact_id,
            "r": risk_level,
            "a": requires_approval,
            "ra": rationale,
            "st": status,
        },
    ).one()
    return PlannedTestRecord(**row._mapping)


def list_tests(db: Session, plan_id: uuid.UUID) -> list[PlannedTestRecord]:
    rows = db.execute(
        text(f"SELECT {_TEST} FROM public.planned_tests WHERE plan_id = :p ORDER BY ordinal"),
        {"p": plan_id},
    ).all()
    return [PlannedTestRecord(**r._mapping) for r in rows]


def delete_tests(db: Session, plan_id: uuid.UUID, test_ids: list[uuid.UUID]) -> int:
    # plan_id scopes the delete: ids from another plan are ignored, never removed.
    result = db.execute(
        text("DELETE FROM public.planned_tests WHERE plan_id = :p AND id = ANY(:ids)"),
        {"p": plan_id, "ids": test_ids},
    )
    return int(result.rowcount)  # type: ignore[attr-defined]


def renumber_tests(db: Session, plan_id: uuid.UUID) -> None:
    # Two passes: the (plan_id, ordinal) unique constraint forbids transient duplicates.
    db.execute(
        text("UPDATE public.planned_tests SET ordinal = ordinal + 100000 WHERE plan_id = :p"),
        {"p": plan_id},
    )
    db.execute(
        text(
            "UPDATE public.planned_tests t SET ordinal = r.n FROM ("
            "SELECT id, ROW_NUMBER() OVER (ORDER BY ordinal) AS n "
            "FROM public.planned_tests WHERE plan_id = :p) r WHERE t.id = r.id"
        ),
        {"p": plan_id},
    )


def update_test_gate(
    db: Session,
    test_id: uuid.UUID,
    *,
    requires_approval: bool | None = None,
    status: str | None = None,
    rationale: str | None = None,
) -> None:
    """Draft-time recomputation: approval need, blocked status and the reason."""
    db.execute(
        text(
            "UPDATE public.planned_tests SET "
            "requires_approval = COALESCE(:a, requires_approval), "
            "status = COALESCE(:s, status), rationale = COALESCE(:r, rationale) WHERE id = :i"
        ),
        {"i": test_id, "a": requires_approval, "s": status, "r": rationale},
    )


def set_tests_status(db: Session, plan_id: uuid.UUID, old: str, new: str) -> None:
    db.execute(
        text("UPDATE public.planned_tests SET status = :n WHERE plan_id = :p AND status = :o"),
        {"p": plan_id, "o": old, "n": new},
    )


# ---- approvals --------------------------------------------------------------------------


def insert_plan_approval(
    db: Session, plan_id: uuid.UUID, risk_level: str, requested_by: uuid.UUID
) -> uuid.UUID:
    row = db.execute(
        text(
            "INSERT INTO public.approvals (plan_id, risk_level, requested_by) "
            "VALUES (:p, :r, :u) RETURNING id"
        ),
        {"p": plan_id, "r": risk_level, "u": requested_by},
    ).one()
    return uuid.UUID(str(row[0]))


def insert_authorization_approval(
    db: Session, authorization_id: uuid.UUID, risk_level: str, requested_by: uuid.UUID
) -> uuid.UUID:
    row = db.execute(
        text(
            "INSERT INTO public.approvals (authorization_id, risk_level, requested_by) "
            "VALUES (:a, :r, :u) RETURNING id"
        ),
        {"a": authorization_id, "r": risk_level, "u": requested_by},
    ).one()
    return uuid.UUID(str(row[0]))


def get_approval(
    db: Session, approval_id: uuid.UUID, *, for_update: bool = False
) -> ApprovalRecord | None:
    # FOR UPDATE OF a: lock only the approval row (the joins are nullable outer joins).
    sql = _APPROVAL_SELECT + "WHERE a.id = :i" + (" FOR UPDATE OF a" if for_update else "")
    row = db.execute(text(sql), {"i": approval_id}).first()
    return ApprovalRecord(**row._mapping) if row else None


def latest_approval_for_plan(db: Session, plan_id: uuid.UUID) -> ApprovalRecord | None:
    row = db.execute(
        text(_APPROVAL_SELECT + "WHERE a.plan_id = :p ORDER BY a.created_at DESC LIMIT 1"),
        {"p": plan_id},
    ).first()
    return ApprovalRecord(**row._mapping) if row else None


def decide_approval(
    db: Session, approval_id: uuid.UUID, *, decision: str, decided_by: uuid.UUID, reason: str | None
) -> None:
    db.execute(
        text(
            "UPDATE public.approvals SET decision = :d, decided_by = :u, reason = :r, "
            "decided_at = now() WHERE id = :i"
        ),
        {"i": approval_id, "d": decision, "u": decided_by, "r": reason},
    )


def list_approvals(
    db: Session, status: str | None, project_ids: list[uuid.UUID] | None, limit: int
) -> list[ApprovalRecord]:
    """Approvals in the given projects (``None`` = every project, Super Admin only; the
    caller decides). Filtering in SQL keeps other projects from filling the page."""
    rows = db.execute(
        text(
            _APPROVAL_SELECT
            + "WHERE (CAST(:s AS text) IS NULL OR a.decision = :s) "
            + "AND (CAST(:ids AS uuid[]) IS NULL "
            + "OR COALESCE(p.project_id, t.project_id) = ANY(CAST(:ids AS uuid[]))) "
            + "ORDER BY a.created_at DESC LIMIT :l"
        ),
        {"s": status, "ids": project_ids, "l": limit},
    ).all()
    return [ApprovalRecord(**r._mapping) for r in rows]


# ---- target authorizations -----------------------------------------------------------------


def insert_authorization(
    db: Session,
    *,
    project_id: uuid.UUID,
    source_id: uuid.UUID,
    environment: str,
    scope: dict[str, Any],
    allowed_risk: list[str],
    requested_by: uuid.UUID,
    justification: str,
    valid_from: datetime,
    valid_until: datetime,
) -> AuthorizationRecord:
    row = db.execute(
        text(
            "INSERT INTO public.target_authorizations (project_id, source_id, environment, "
            "scope, allowed_risk, requested_by, justification, valid_from, valid_until) "
            "VALUES (:p, :s, :e, CAST(:sc AS jsonb), :ar, :u, :j, :vf, :vu) "
            f"RETURNING {_AUTH}"
        ),
        {
            "p": project_id,
            "s": source_id,
            "e": environment,
            "sc": json.dumps(scope),
            "ar": allowed_risk,
            "u": requested_by,
            "j": justification,
            "vf": valid_from,
            "vu": valid_until,
        },
    ).one()
    return AuthorizationRecord(**row._mapping)


def get_authorization(
    db: Session, project_id: uuid.UUID, authorization_id: uuid.UUID, *, for_update: bool = False
) -> AuthorizationRecord | None:
    sql = f"SELECT {_AUTH} FROM public.target_authorizations WHERE id = :i AND project_id = :p" + (
        " FOR UPDATE" if for_update else ""
    )
    row = db.execute(text(sql), {"i": authorization_id, "p": project_id}).first()
    return AuthorizationRecord(**row._mapping) if row else None


def list_authorizations(db: Session, project_id: uuid.UUID) -> list[AuthorizationRecord]:
    rows = db.execute(
        text(
            f"SELECT {_AUTH} FROM public.target_authorizations WHERE project_id = :p "
            "ORDER BY created_at DESC, id"
        ),
        {"p": project_id},
    ).all()
    return [AuthorizationRecord(**r._mapping) for r in rows]


def pending_authorization(
    db: Session, project_id: uuid.UUID, source_id: uuid.UUID, environment: str
) -> bool:
    return (
        db.execute(
            text(
                "SELECT 1 FROM public.target_authorizations WHERE project_id = :p "
                "AND source_id = :s AND environment = :e AND status = 'pending'"
            ),
            {"p": project_id, "s": source_id, "e": environment},
        ).first()
        is not None
    )


def decide_authorization(
    db: Session,
    authorization_id: uuid.UUID,
    *,
    status: str,
    decided_by: uuid.UUID,
    note: str | None,
) -> AuthorizationRecord:
    row = db.execute(
        text(
            "UPDATE public.target_authorizations SET status = :s, decided_by = :u, "
            f"decision_note = :n, decided_at = now() WHERE id = :i RETURNING {_AUTH}"
        ),
        {"i": authorization_id, "s": status, "u": decided_by, "n": note},
    ).one()
    return AuthorizationRecord(**row._mapping)


def revoke_authorization(db: Session, authorization_id: uuid.UUID) -> AuthorizationRecord:
    row = db.execute(
        text(
            "UPDATE public.target_authorizations SET status = 'revoked' "
            f"WHERE id = :i RETURNING {_AUTH}"
        ),
        {"i": authorization_id},
    ).one()
    return AuthorizationRecord(**row._mapping)


def valid_authorizations_for_source(
    db: Session, project_id: uuid.UUID, source_id: uuid.UUID
) -> list[AuthorizationRecord]:
    """Approved authorizations whose window contains *now* (database clock)."""
    rows = db.execute(
        text(
            f"SELECT {_AUTH} FROM public.target_authorizations WHERE project_id = :p "
            "AND source_id = :s AND status = 'approved' "
            "AND valid_from <= now() AND valid_until > now() ORDER BY valid_until DESC"
        ),
        {"p": project_id, "s": source_id},
    ).all()
    return [AuthorizationRecord(**r._mapping) for r in rows]


def script_artifact_usable(db: Session, project_id: uuid.UUID, artifact_id: uuid.UUID) -> bool:
    """A project's own accepted ``script`` artifact (never another project's)."""
    return (
        db.execute(
            text(
                "SELECT 1 FROM public.artifacts WHERE id = :a AND project_id = :p "
                "AND kind = 'script' AND validation_status = 'accepted' AND deleted_at IS NULL"
            ),
            {"a": artifact_id, "p": project_id},
        ).first()
        is not None
    )
