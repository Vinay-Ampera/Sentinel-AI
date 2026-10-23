import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from sentinel_ai.repositories.findings import (
    AttemptRecord,
    FindingEventRecord,
    FindingEvidenceRecord,
    FindingRecord,
    GroupRecord,
)
from sentinel_ai.services.findings import FindingDetail

Status = Literal["triaged", "in_progress", "fixed", "accepted_risk", "false_positive", "reopened"]
Verification = Literal["likely", "confirmed", "not_reproduced", "inconclusive"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StatusRequest(_Strict):
    status: Status
    note: str | None = Field(default=None, max_length=2000)


class VerificationRequest(_Strict):
    state: Verification
    note: str = Field(min_length=1, max_length=2000)


class FindingOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    first_run_id: uuid.UUID | None
    last_run_id: uuid.UUID | None
    result_id: uuid.UUID | None
    title: str
    description: str | None
    category: str
    detected_by: str
    rule_id: str | None
    file_path: str | None
    line_number: int | None
    severity: str
    confidence: str
    verification_state: str
    status: str
    limitations: str | None
    occurrences: int
    cwe: int | None
    component: str | None
    aliases: list[str]
    group_id: uuid.UUID | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, f: FindingRecord) -> "FindingOut":
        return cls(**{k: getattr(f, k) for k in cls.model_fields})


class FindingEventOut(BaseModel):
    id: int
    event_type: str
    from_value: str | None
    to_value: str | None
    actor_user_id: uuid.UUID | None
    detail: dict[str, Any]
    created_at: datetime

    @classmethod
    def of(cls, e: FindingEventRecord) -> "FindingEventOut":
        return cls(**{k: getattr(e, k) for k in cls.model_fields})


class FindingEvidenceOut(BaseModel):
    artifact_id: uuid.UUID
    filename: str | None
    kind: str
    size_bytes: int
    note: str | None
    run_id: uuid.UUID | None

    @classmethod
    def of(cls, e: FindingEvidenceRecord) -> "FindingEvidenceOut":
        return cls(**{k: getattr(e, k) for k in cls.model_fields})


class AttemptOut(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    outcome: str
    method: str
    notes: str | None
    evidence_artifact_id: uuid.UUID | None
    created_at: datetime

    @classmethod
    def of(cls, a: AttemptRecord) -> "AttemptOut":
        return cls(**{k: getattr(a, k) for k in cls.model_fields})


class GroupMemberOut(BaseModel):
    id: uuid.UUID
    title: str
    detected_by: str
    rule_id: str | None
    severity: str
    confidence: str
    status: str
    verification_state: str
    file_path: str | None
    line_number: int | None
    component: str | None

    @classmethod
    def of(cls, f: FindingRecord) -> "GroupMemberOut":
        return cls(**{k: getattr(f, k) for k in cls.model_fields})


class FindingGroupOut(BaseModel):
    """Findings several tools (or advisories) report for one issue. Each member keeps its own
    tool, evidence and state; the group only says they probably describe the same thing."""

    id: uuid.UUID
    kind: str
    tools: list[str]
    severity: str
    members: list[GroupMemberOut]

    @classmethod
    def of(cls, g: GroupRecord) -> "FindingGroupOut":
        rank = ["critical", "high", "medium", "low", "info"]
        return cls(
            id=g.id,
            kind=g.kind,
            tools=sorted({m.detected_by for m in g.members}),
            severity=min((m.severity for m in g.members), key=rank.index, default="info"),
            members=[GroupMemberOut.of(m) for m in g.members],
        )


class FindingDetailOut(FindingOut):
    events: list[FindingEventOut]
    evidence: list[FindingEvidenceOut]
    attempts: list[AttemptOut]
    related: list[GroupMemberOut]

    @classmethod
    def from_detail(cls, d: FindingDetail) -> "FindingDetailOut":
        base = FindingOut.of(d.finding).model_dump()
        return cls(
            **base,
            events=[FindingEventOut.of(e) for e in d.events],
            evidence=[FindingEvidenceOut.of(e) for e in d.evidence],
            attempts=[AttemptOut.of(a) for a in d.attempts],
            related=[GroupMemberOut.of(r) for r in d.related],
        )
