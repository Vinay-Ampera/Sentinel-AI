"""Reviewing drafted regression tests (Stage 11). Accepting or rejecting records a decision
and an audit event; it never writes to a source tree, commits, or runs anything."""

import uuid

from sqlalchemy.orm import Session

from sentinel_ai.core.errors import DomainError
from sentinel_ai.repositories import regression_tests as repo
from sentinel_ai.repositories.identity import UserRecord
from sentinel_ai.services import audit
from sentinel_ai.services.audit import RequestContext

DECISIONS = ("accepted", "rejected")
MAX_NOTE = 1000


def list_proposals(
    db: Session, project_id: uuid.UUID, status: str | None, limit: int
) -> list[repo.ProposalRecord]:
    return repo.list_for_project(db, project_id, status, limit)


def get_proposal(db: Session, project_id: uuid.UUID, proposal_id: uuid.UUID) -> repo.ProposalRecord:
    found = repo.get(db, project_id, proposal_id)  # scoped by project
    if found is None:
        raise DomainError(404, "not_found", "Regression proposal not found")
    return found


def decide(
    db: Session,
    ctx: RequestContext,
    user: UserRecord,
    project_id: uuid.UUID,
    proposal_id: uuid.UUID,
    *,
    decision: str,
    note: str | None,
) -> repo.ProposalRecord:
    if decision not in DECISIONS:
        raise DomainError(422, "validation_failed", "decision must be accepted or rejected")
    cleaned = " ".join(note.split()) if note else None
    if cleaned and len(cleaned) > MAX_NOTE:
        raise DomainError(422, "validation_failed", f"note must be at most {MAX_NOTE} characters")
    current = get_proposal(db, project_id, proposal_id)
    if current.status != "proposed":
        raise DomainError(409, "already_decided", f"This proposal is already {current.status}")
    if not repo.decide(
        db, project_id, proposal_id, status=decision, decided_by=user.id, note=cleaned or None
    ):
        raise DomainError(409, "already_decided", "This proposal was decided meanwhile")
    audit.record(
        db, ctx, action="regression.decision", outcome="success", actor_user_id=user.id,
        project_id=project_id, target_type="regression_test", target_id=str(proposal_id),
        detail={"decision": decision, "framework": current.framework,
                "target_path": current.target_path, "risk_flags": current.risk_flags},
    )  # fmt: skip
    db.commit()
    return get_proposal(db, project_id, proposal_id)
