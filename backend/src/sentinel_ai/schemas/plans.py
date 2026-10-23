import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from sentinel_ai.repositories.plans import (
    ApprovalRecord,
    AuthorizationRecord,
    PlannedTestRecord,
    PlanRecord,
)
from sentinel_ai.services.check_catalog import RISK_DEFINITIONS
from sentinel_ai.services.plans import DevTestInput, PlanDetail
from sentinel_ai.services.policy import EffectivePolicy


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DevTestRequest(_Strict):
    """A catalog check chosen by a developer. There is deliberately no field for a command,
    a risk level or an approval flag: those come from the catalog and policy."""

    check_id: str = Field(min_length=1, max_length=100)
    source_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=300)
    parameters: dict[str, Any] = Field(default_factory=dict, max_length=5)
    script_artifact_id: uuid.UUID | None = None

    def to_input(self) -> DevTestInput:
        return DevTestInput(
            self.check_id, self.source_id, self.name, self.parameters, self.script_artifact_id
        )


class CreatePlanRequest(_Strict):
    mode: str
    snapshot_id: uuid.UUID | None = None
    prompt: str | None = Field(default=None, max_length=2000)
    tests: list[DevTestRequest] = Field(default_factory=list, max_length=60)


class UpdatePlanRequest(_Strict):
    summary: str | None = Field(default=None, max_length=2000)
    remove_test_ids: list[uuid.UUID] = Field(default_factory=list, max_length=60)
    add_tests: list[DevTestRequest] = Field(default_factory=list, max_length=60)


class DecisionRequest(_Strict):
    decision: str
    reason: str | None = Field(default=None, max_length=2000)


class AuthorizationRequestBody(_Strict):
    environment: str
    paths: list[str] = Field(default_factory=lambda: ["/"], max_length=20)
    methods: list[str] = Field(default_factory=lambda: ["GET", "HEAD", "OPTIONS"], max_length=7)
    allowed_risk: list[str] = Field(default_factory=lambda: ["low"], max_length=3)
    valid_from: datetime | None = None
    valid_until: datetime
    justification: str = Field(min_length=10, max_length=2000)


class PolicyValueRequest(_Strict):
    value: Any


class PlannedTestOut(BaseModel):
    id: uuid.UUID
    ordinal: int
    name: str
    category: str
    tool: str
    origin: str
    risk_level: str
    requires_approval: bool
    status: str
    rationale: str | None
    target: dict[str, Any] | None
    prerequisites: list[str]
    expected_evidence: list[str]
    parameters: dict[str, Any]
    script_artifact_id: uuid.UUID | None

    @classmethod
    def from_record(cls, t: PlannedTestRecord) -> "PlannedTestOut":
        d = t.definition
        return cls(
            id=t.id,
            ordinal=t.ordinal,
            name=t.name,
            category=t.category,
            tool=t.tool,
            origin=t.origin,
            risk_level=t.risk_level,
            requires_approval=t.requires_approval,
            status=t.status,
            rationale=t.rationale,
            target=d.get("target"),
            prerequisites=list(d.get("prerequisites", [])),
            expected_evidence=list(d.get("expected_evidence", [])),
            parameters=dict(d.get("parameters", {})),
            script_artifact_id=t.script_artifact_id,
        )


class ApprovalOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    kind: str
    plan_id: uuid.UUID | None
    authorization_id: uuid.UUID | None
    risk_level: str
    decision: str
    requested_by: uuid.UUID
    decided_by: uuid.UUID | None
    reason: str | None
    created_at: datetime
    decided_at: datetime | None

    @classmethod
    def from_record(cls, a: ApprovalRecord) -> "ApprovalOut":
        return cls(kind="plan" if a.plan_id else "authorization", **a.__dict__)


class PlanSummaryOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    snapshot_id: uuid.UUID | None
    version: int
    mode: str
    status: str
    risk_level: str
    summary: str | None
    created_by: uuid.UUID
    created_at: datetime
    submitted_at: datetime | None

    @classmethod
    def from_record(cls, p: PlanRecord) -> "PlanSummaryOut":
        return cls(
            id=p.id,
            project_id=p.project_id,
            snapshot_id=p.snapshot_id,
            version=p.version,
            mode=p.plan_mode,
            status=p.status,
            risk_level=p.risk_level,
            summary=p.summary,
            created_by=p.created_by,
            created_at=p.created_at,
            submitted_at=p.submitted_at,
        )


class PlanOut(PlanSummaryOut):
    prompt: str | None
    content_sha256: str | None
    policy_snapshot: dict[str, Any] | None
    tests: list[PlannedTestOut]
    counts: dict[str, int]
    approval: ApprovalOut | None
    execution_available: bool
    notice: str
    viewer_can_approve: bool

    @classmethod
    def from_detail(cls, d: PlanDetail, viewer_can_approve: bool = False) -> "PlanOut":
        counts: dict[str, int] = {}
        for t in d.tests:
            counts[t.status] = counts.get(t.status, 0) + 1
        base = PlanSummaryOut.from_record(d.plan)
        return cls(
            **base.model_dump(),
            prompt=d.plan.prompt,
            content_sha256=d.plan.content_sha256,
            policy_snapshot=d.plan.policy_snapshot,
            tests=[PlannedTestOut.from_record(t) for t in d.tests],
            counts=counts,
            approval=ApprovalOut.from_record(d.approval) if d.approval else None,
            execution_available=False,
            viewer_can_approve=viewer_can_approve,
            notice=(
                "Planning only: no test runner is connected yet, so nothing has been executed. "
                "Approval makes a plan eligible for a later run; it does not start one."
            ),
        )


class AuthorizationOut(BaseModel):
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
    in_effect: bool

    @classmethod
    def from_record(cls, a: AuthorizationRecord, now: datetime) -> "AuthorizationOut":
        in_effect = bool(
            a.status == "approved"
            and a.valid_from
            and a.valid_until
            and a.valid_from <= now < a.valid_until
        )
        return cls(**a.__dict__, in_effect=in_effect)


class EffectivePolicyOut(BaseModel):
    production_testing: dict[str, bool]
    approval_required_risk_levels: list[str]
    allowed_risk_levels: list[str]
    high_risk_approver_roles: list[str]
    risk_approvers: dict[str, list[str]]
    risk_definitions: dict[str, str]

    @classmethod
    def from_policy(cls, p: EffectivePolicy) -> "EffectivePolicyOut":
        return cls(**p.snapshot(), risk_definitions=RISK_DEFINITIONS)
