import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from sentinel_ai.repositories.runs import BatchRecord, EventRecord, ResultRecord, RunRecord
from sentinel_ai.services.runs import RunView


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateRunRequest(_Strict):
    """Only the plan and an optional time limit. There is deliberately no field for a
    command, a risk level or an approval flag: those belong to the approved plan."""

    plan_id: uuid.UUID
    timeout_seconds: int | None = Field(default=None, ge=60, le=86400)


class ProgressOut(BaseModel):
    batches_total: int
    batches_by_status: dict[str, int]
    tests_total: int
    results_by_status: dict[str, int]
    tests_finished: int


class RunOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    plan_id: uuid.UUID
    parent_run_id: uuid.UUID | None
    kind: str
    status: str
    requested_by: uuid.UUID
    timeout_seconds: int
    cancel_requested_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_summary: str | None
    created_at: datetime
    progress: ProgressOut | None = None

    @classmethod
    def of(cls, run: RunRecord) -> "RunOut":
        return cls(**{k: getattr(run, k) for k in cls.model_fields if k != "progress"})

    @classmethod
    def from_view(cls, view: RunView) -> "RunOut":
        out = cls.of(view.run)
        p = view.progress
        if p is not None:
            out.progress = ProgressOut(
                batches_total=p.batches_total,
                batches_by_status=p.batches_by_status,
                tests_total=p.tests_total,
                results_by_status=p.results_by_status,
                tests_finished=sum(p.results_by_status.values()),
            )
        return out


class BatchOut(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    ordinal: int
    status: str
    attempt: int
    max_attempts: int
    timeout_seconds: int
    started_at: datetime | None
    finished_at: datetime | None
    heartbeat_at: datetime | None
    error_code: str | None
    error_summary: str | None

    @classmethod
    def of(cls, b: BatchRecord) -> "BatchOut":
        return cls(**{k: getattr(b, k) for k in cls.model_fields})


class ResultOut(BaseModel):
    id: uuid.UUID
    batch_id: uuid.UUID
    planned_test_id: uuid.UUID
    attempt: int
    status: str
    summary: str | None
    exit_code: int | None
    duration_ms: int | None
    finished_at: datetime | None

    @classmethod
    def of(cls, r: ResultRecord) -> "ResultOut":
        return cls(**{k: getattr(r, k) for k in cls.model_fields})


class EventOut(BaseModel):
    id: int
    batch_id: uuid.UUID | None
    event_type: str
    from_status: str | None
    to_status: str | None
    actor_user_id: uuid.UUID | None
    detail: dict[str, Any]
    created_at: datetime

    @classmethod
    def of(cls, e: EventRecord) -> "EventOut":
        return cls(**{k: getattr(e, k) for k in cls.model_fields})
