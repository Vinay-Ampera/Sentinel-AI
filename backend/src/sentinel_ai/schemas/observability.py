"""API shapes for event ingestion, ingest keys, groups and alerts (Stage 12, ADR-0011).

``EventIn`` is the strict, bounded event schema v1: unknown fields are refused, every field has
a size or format limit, and nothing in it can name a command, a path or a risk level."""

import math
import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Level = Literal["debug", "info", "warning", "error", "fatal"]
Environment = Literal["local", "development", "staging", "production", "unknown"]
MAX_STACK_FRAMES = 60
_ATTR_KEY = re.compile(r"^[a-z0-9_.-]{1,40}$")
_FRAME = re.compile(r"^\s*(?:File\s|at\s)", re.M)


class EventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: uuid.UUID | None = None
    timestamp: datetime | None = None
    level: Level
    service: str = Field(pattern=r"^[A-Za-z0-9._-]{1,64}$")
    environment: Environment = "unknown"
    message: str = Field(min_length=1, max_length=2048)
    error_type: str | None = Field(default=None, min_length=1, max_length=128)
    stack: str | None = Field(default=None, min_length=1, max_length=8192)
    attributes: dict[str, str | int | float | bool] = Field(default_factory=dict, max_length=20)
    trace_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    span_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{16}$")
    release: str | None = Field(default=None, min_length=1, max_length=64)
    run_id: uuid.UUID | None = None
    result_id: uuid.UUID | None = None
    finding_id: uuid.UUID | None = None

    @field_validator("attributes")
    @classmethod
    def _attributes(cls, value: dict[str, Any]) -> dict[str, Any]:
        for key, item in value.items():
            if not _ATTR_KEY.match(key):
                raise ValueError("attribute keys must match [a-z0-9_.-]{1,40}")
            if isinstance(item, str) and len(item) > 256:
                raise ValueError("attribute values must be at most 256 characters")
            if isinstance(item, float) and not math.isfinite(item):
                raise ValueError("attribute numbers must be finite")
        return value

    @field_validator("stack")
    @classmethod
    def _stack(cls, value: str | None) -> str | None:
        if value is not None and len(_FRAME.findall(value)) > MAX_STACK_FRAMES:
            raise ValueError(f"stack must have at most {MAX_STACK_FRAMES} frames")
        return value


class IngestResponse(BaseModel):
    accepted: int
    dropped: dict[str, int]


class CreateIngestKeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=80)
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


class IngestKeyOut(BaseModel):
    id: uuid.UUID
    key_id: str
    label: str
    created_by: uuid.UUID | None
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None
    status: Literal["active", "expired", "revoked"]


class CreatedIngestKeyOut(IngestKeyOut):
    key: str  # shown once; only a hash is stored


class GroupOut(BaseModel):
    id: uuid.UUID
    service: str
    environment: str
    level_class: str
    error_type: str | None
    message: str  # the normalized message (volatile parts replaced)
    first_seen: datetime
    last_seen: datetime
    total_count: int
    has_stack: bool
    is_overflow: bool
    fingerprint_version: str


class SampleOut(BaseModel):
    id: uuid.UUID
    received_at: datetime
    client_timestamp: datetime | None
    timestamp_untrusted: bool
    level: str
    service: str
    environment: str
    message: str
    error_type: str | None
    stack: str | None
    attributes: dict[str, Any]
    trace_id: str | None
    span_id: str | None
    release: str | None
    correlation: dict[str, Any]
    redactions: dict[str, int]
    reported_by: Literal["application"] = "application"


class GroupDetailOut(GroupOut):
    samples: list[SampleOut]
    limits: list[str]


class AlertOut(BaseModel):
    id: uuid.UUID
    rule: str
    rule_version: str
    source: Literal["external", "internal"]
    severity: str
    status: str
    title: str
    measured: dict[str, Any]
    evidence: dict[str, Any]
    confidence: Literal["observed"] = "observed"
    cause_status: str
    next_action: str
    occurrences: int
    group_id: uuid.UUID | None
    run_id: uuid.UUID | None
    result_id: uuid.UUID | None
    finding_id: uuid.UUID | None
    agent_run_id: uuid.UUID | None
    first_seen: datetime
    last_seen: datetime
    closed_at: datetime | None


class AlertHistoryOut(BaseModel):
    action: str
    actor_user_id: uuid.UUID | None
    note: str | None
    detail: dict[str, Any]
    created_at: datetime


class AlertDetailOut(AlertOut):
    history: list[AlertHistoryOut]
    group: GroupOut | None
    proposal_ids: list[uuid.UUID]
    telemetry: dict[str, Any]
    cause_note: str


class AlertNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = Field(default=None, max_length=1000)
