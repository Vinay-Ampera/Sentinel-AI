import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from sentinel_ai.core.permissions import AccessLevel
from sentinel_ai.repositories.projects import (
    MemberRecord,
    ProjectRecord,
    SnapshotRecord,
    SourceRecord,
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateProjectRequest(_Strict):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    application_type: str


class UpdateProjectRequest(_Strict):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)


class MemberRequest(_Strict):
    access_level: str


class UrlSourceRequest(_Strict):
    """Descriptor for a non-upload source. Which fields are required depends on source_type;
    the service validates the combination and rejects anything extra."""

    source_type: str
    name: str = Field(min_length=1, max_length=200)
    git_url: str | None = Field(default=None, max_length=2048)
    git_ref: str | None = Field(default=None, max_length=200)
    target_url: str | None = Field(default=None, max_length=2048)
    environment: str | None = Field(default=None, max_length=20)


class AnalysisRequest(_Strict):
    source_id: uuid.UUID


class ProjectOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    owner_user_id: uuid.UUID
    application_type: str
    status: str
    created_at: datetime
    updated_at: datetime
    your_access: str | None = None

    @classmethod
    def from_record(cls, p: ProjectRecord, access: AccessLevel | None = None) -> "ProjectOut":
        return cls(**p.__dict__, your_access=access.name.lower() if access else None)


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    display_name: str
    access_level: str
    created_at: datetime

    @classmethod
    def from_record(cls, m: MemberRecord) -> "MemberOut":
        return cls(**m.__dict__)


class SourceOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    source_type: str
    name: str
    is_active: bool
    size_bytes: int | None
    sha256: str | None
    git_url: str | None = None
    git_ref: str | None = None
    target_url: str | None = None
    environment: str | None = None
    created_at: datetime

    @classmethod
    def from_record(cls, s: SourceRecord) -> "SourceOut":
        return cls(
            git_url=s.git_url,
            git_ref=s.git_ref,
            target_url=s.target_url,
            environment=s.environment,
            id=s.id,
            project_id=s.project_id,
            source_type=s.source_type,
            name=s.name,
            is_active=s.is_active,
            size_bytes=s.size_bytes,
            sha256=s.sha256,
            created_at=s.created_at,
        )


class SnapshotOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    source_id: uuid.UUID
    content_sha256: str | None
    status: str
    error_summary: str | None
    created_at: datetime
    completed_at: datetime | None
    result: dict[str, Any]

    @classmethod
    def from_record(cls, s: SnapshotRecord) -> "SnapshotOut":
        return cls(
            id=s.id,
            project_id=s.project_id,
            source_id=s.source_id,
            content_sha256=s.content_sha256,
            status=s.status,
            error_summary=s.error_summary,
            created_at=s.created_at,
            completed_at=s.completed_at,
            result=s.detected,
        )
