"""Request/response models for identity endpoints. Responses are explicit allow-lists:
password hashes, token hashes, and lockout counters are never serialised."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from sentinel_ai.repositories.identity import SessionRecord, UserRecord


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginRequest(_Strict):
    email: str = Field(max_length=320)
    password: SecretStr = Field(max_length=1024)


class PasswordChangeRequest(_Strict):
    current: SecretStr = Field(max_length=1024)
    new: SecretStr = Field(max_length=1024)


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    role: str

    @classmethod
    def from_record(cls, user: UserRecord) -> "UserOut":
        return cls(
            id=user.id, email=user.email, display_name=user.display_name, role=user.role_name
        )


class AdminUserOut(UserOut):
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime

    @classmethod
    def from_record(cls, user: UserRecord) -> "AdminUserOut":
        return cls(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            role=user.role_name,
            is_active=user.is_active,
            last_login_at=user.last_login_at,
            created_at=user.created_at,
        )


class SessionOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    ip_address: str | None
    user_agent: str | None
    current: bool

    @classmethod
    def from_record(cls, record: SessionRecord, current_id: uuid.UUID) -> "SessionOut":
        return cls(
            id=record.id,
            created_at=record.created_at,
            last_seen_at=record.last_seen_at,
            idle_expires_at=record.idle_expires_at,
            absolute_expires_at=record.absolute_expires_at,
            ip_address=record.ip_address,
            user_agent=record.user_agent,
            current=record.id == current_id,
        )


class CreateUserRequest(_Strict):
    email: str = Field(max_length=320)
    display_name: str = Field(min_length=1, max_length=200)
    role: str = "developer"
    password: SecretStr = Field(max_length=1024)


class UpdateUserRequest(_Strict):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None
    role: str | None = None
