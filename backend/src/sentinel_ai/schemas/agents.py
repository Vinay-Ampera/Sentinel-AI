"""API shapes for agent workflow runs and regression proposals (Stage 11)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sentinel_ai.repositories.agent_runs import AgentRunRecord, AgentStepRecord
from sentinel_ai.repositories.regression_tests import ProposalRecord
from sentinel_ai.services.agent_workflows import AgentRunDetail

Workflow = Literal["planning", "analysis", "investigation", "regression", "verification"]


class CreateAgentRunRequest(BaseModel):
    """One shape for every workflow; the combination of fields is checked per workflow.

    planning: prompt (+ optional snapshot_id) · analysis: snapshot_id · investigation and
    regression: exactly one of result_id / finding_id · verification: finding_id and
    mode=prepare, or mode=conclude with run_id (+ optional summarize)."""

    model_config = ConfigDict(extra="forbid")
    workflow: Workflow
    prompt: str | None = Field(default=None, min_length=1, max_length=2000)
    snapshot_id: uuid.UUID | None = None
    result_id: uuid.UUID | None = None
    finding_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None
    mode: Literal["prepare", "conclude"] | None = None
    summarize: bool = False

    @model_validator(mode="after")
    def _combination(self) -> "CreateAgentRunRequest":
        given = {
            k for k in ("prompt", "snapshot_id", "result_id", "finding_id", "run_id", "mode")
            if getattr(self, k) is not None
        } | ({"summarize"} if self.summarize else set())  # fmt: skip
        allowed, required = _RULES[self.workflow]
        extra = given - allowed
        if extra:
            raise ValueError(f"{', '.join(sorted(extra))} not allowed for {self.workflow}")
        missing = required - given
        if missing:
            raise ValueError(f"{', '.join(sorted(missing))} required for {self.workflow}")
        if self.workflow in ("investigation", "regression") and (self.result_id is None) == (
            self.finding_id is None
        ):
            raise ValueError("give exactly one of result_id or finding_id")
        if self.workflow == "verification":
            if self.mode == "conclude" and self.run_id is None:
                raise ValueError("run_id is required to conclude verification")
            if self.mode == "prepare" and (self.run_id is not None or self.summarize):
                raise ValueError("run_id and summarize apply only when concluding")
        return self


_RULES: dict[str, tuple[set[str], set[str]]] = {
    "planning": ({"prompt", "snapshot_id"}, {"prompt"}),
    "analysis": ({"snapshot_id"}, {"snapshot_id"}),
    "investigation": ({"result_id", "finding_id"}, set()),
    "regression": ({"result_id", "finding_id"}, set()),
    "verification": ({"finding_id", "mode", "run_id", "summarize"}, {"finding_id", "mode"}),
}


class AgentStepOut(BaseModel):
    seq: int
    node: str
    kind: str
    outcome: str
    detail: dict[str, Any]
    llm_usage_id: int | None
    created_at: datetime

    @classmethod
    def from_record(cls, s: AgentStepRecord) -> "AgentStepOut":
        return cls(seq=s.seq, node=s.node, kind=s.kind, outcome=s.outcome, detail=s.detail,
                   llm_usage_id=s.llm_usage_id, created_at=s.created_at)  # fmt: skip


class AgentRunOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    workflow: str
    status: str
    degraded_reason: str | None
    used_llm: bool
    cache_hit: bool
    model: str | None
    plan_id: str | None
    check_ids: list[str]
    source: str | None
    message: str | None
    result: dict[str, Any] | None
    started_at: datetime
    finished_at: datetime | None
    steps: list[AgentStepOut] | None = None

    @classmethod
    def from_record(
        cls, r: AgentRunRecord, steps: list[AgentStepRecord] | None = None
    ) -> "AgentRunOut":
        result = r.result or {}
        return cls(
            id=r.id, project_id=r.project_id, workflow=r.workflow, status=r.status,
            degraded_reason=r.degraded_reason, used_llm=r.used_llm, cache_hit=r.cache_hit,
            model=r.model, plan_id=result.get("plan_id"), check_ids=result.get("check_ids", []),
            source=result.get("source"), message=result.get("message") or result.get("reason"),
            result=r.result, started_at=r.started_at, finished_at=r.finished_at,
            steps=None if steps is None else [AgentStepOut.from_record(s) for s in steps],
        )  # fmt: skip

    @classmethod
    def from_detail(cls, d: AgentRunDetail) -> "AgentRunOut":
        return cls.from_record(d.run, d.steps)


class RegressionProposalOut(BaseModel):
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
    code: str  # text for review; Sentinel never writes or runs it
    expected_behavior: str
    evidence_ids: list[str]
    risk_flags: list[str]
    overlap: list[str]
    decided_by: uuid.UUID | None
    decision_note: str | None
    created_at: datetime
    decided_at: datetime | None

    @classmethod
    def from_record(cls, p: ProposalRecord) -> "RegressionProposalOut":
        return cls(
            id=p.id, project_id=p.project_id, finding_id=p.finding_id, result_id=p.result_id,
            agent_run_id=p.agent_run_id, status=p.status, title=p.title, rationale=p.rationale,
            target_path=p.target_path, framework=p.framework, code=p.code,
            expected_behavior=p.expected_behavior, evidence_ids=p.evidence_ids,
            risk_flags=p.risk_flags, overlap=p.overlap, decided_by=p.decided_by,
            decision_note=p.decision_note, created_at=p.created_at, decided_at=p.decided_at,
        )  # fmt: skip


class ProposalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["accepted", "rejected"]
    note: str | None = Field(default=None, max_length=1000)
