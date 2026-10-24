"""SQL for drafted regression tests (``public.regression_tests``; draft columns added by 0009).

A row is a *proposal*: text for a person to accept or reject. Nothing here writes to a source
tree or runs anything."""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

_COLS = (
    "id, project_id, finding_id, result_id, agent_run_id, status, title, rationale, target_path, "
    "framework, code, expected_behavior, evidence_ids, risk_flags, overlap, proposed_by, "
    "decided_by, decision_note, created_at, decided_at"
)


@dataclass(frozen=True)
class ProposalRecord:
    id: uuid.UUID
    project_id: uuid.UUID
    finding_id: uuid.UUID | None
    result_id: uuid.UUID | None
    agent_run_id: uuid.UUID | None
    status: str
    title: str
    rationale: str
    target_path: str
    framework: str
    code: str
    expected_behavior: str
    evidence_ids: list[str]
    risk_flags: list[str]
    overlap: list[str]
    proposed_by: uuid.UUID | None
    decided_by: uuid.UUID | None
    decision_note: str | None
    created_at: datetime
    decided_at: datetime | None


def insert(
    db: Session,
    *,
    project_id: uuid.UUID,
    finding_id: uuid.UUID | None,
    result_id: uuid.UUID | None,
    agent_run_id: uuid.UUID,
    proposed_by: uuid.UUID,
    draft: dict[str, Any],
) -> uuid.UUID:
    row = db.execute(
        text(
            "INSERT INTO public.regression_tests (project_id, finding_id, result_id, "
            "agent_run_id, proposed_by, title, rationale, target_path, framework, code, "
            "expected_behavior, evidence_ids, risk_flags, overlap) VALUES (:p, :f, :r, :a, :u, "
            ":t, :ra, :tp, :fw, :c, :eb, CAST(:ev AS jsonb), CAST(:rf AS jsonb), "
            "CAST(:ov AS jsonb)) RETURNING id"
        ),
        {
            "p": project_id,
            "f": finding_id,
            "r": result_id,
            "a": agent_run_id,
            "u": proposed_by,
            "t": draft["title"],
            "ra": draft["rationale"],
            "tp": draft["target_path"],
            "fw": draft["framework"],
            "c": draft["code"],
            "eb": draft["expected_behavior"],
            "ev": json.dumps(draft["evidence_ids"]),
            "rf": json.dumps(draft["risk_flags"]),
            "ov": json.dumps(draft["overlap"]),
        },
    ).one()
    return row.id  # type: ignore[no-any-return]


def get(db: Session, project_id: uuid.UUID, proposal_id: uuid.UUID) -> ProposalRecord | None:
    row = db.execute(
        text(f"SELECT {_COLS} FROM public.regression_tests WHERE id = :i AND project_id = :p"),
        {"i": proposal_id, "p": project_id},
    ).first()
    return ProposalRecord(**row._mapping) if row else None


def list_for_project(
    db: Session, project_id: uuid.UUID, status: str | None, limit: int
) -> list[ProposalRecord]:
    rows = db.execute(
        text(
            f"SELECT {_COLS} FROM public.regression_tests WHERE project_id = :p "
            "AND (CAST(:s AS text) IS NULL OR status = :s) ORDER BY created_at DESC, id LIMIT :n"
        ),
        {"p": project_id, "s": status, "n": limit},
    ).all()
    return [ProposalRecord(**r._mapping) for r in rows]


def decide(
    db: Session,
    project_id: uuid.UUID,
    proposal_id: uuid.UUID,
    *,
    status: str,
    decided_by: uuid.UUID,
    note: str | None,
) -> bool:
    """Only a ``proposed`` row can be decided, once."""
    result = db.execute(
        text(
            "UPDATE public.regression_tests SET status = :s, decided_by = :u, decision_note = :n, "
            "decided_at = now() WHERE id = :i AND project_id = :p AND status = 'proposed'"
        ),
        {"s": status, "u": decided_by, "n": note, "i": proposal_id, "p": project_id},
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


def find_existing_for_input(
    db: Session, project_id: uuid.UUID, input_hash: str
) -> uuid.UUID | None:
    """A live proposal drafted from exactly the same evidence (so asking again does not spend
    another model call or create a duplicate)."""
    row = db.execute(
        text(
            "SELECT rt.id FROM public.agent_runs ar JOIN public.regression_tests rt "
            "ON rt.agent_run_id = ar.id WHERE ar.project_id = :p AND ar.workflow = 'regression' "
            "AND ar.input_hash = :h AND rt.status IN ('proposed', 'accepted') "
            "ORDER BY ar.created_at DESC LIMIT 1"
        ),
        {"p": project_id, "h": input_hash},
    ).first()
    return row.id if row else None
