"""Plain data types shared by the gateway and its providers."""

import uuid
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel

from sentinel_ai.services.audit import RequestContext

PURPOSES = ("analysis", "planning", "investigation", "regression", "verification", "chat", "other")


@dataclass(frozen=True)
class ProviderRequest:
    """What a provider receives: text that is already redacted, plus the schema it must follow."""

    system: str
    prompt: str
    output_schema: type[BaseModel]
    max_output_tokens: int
    model: str


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    input_tokens: int | None  # None = the provider did not report it
    output_tokens: int | None


class LLMProvider(Protocol):
    """The only thing the gateway needs from a model vendor. Implementations must honour
    ``timeout_seconds`` and raise ``ProviderError`` subclasses; they must not retry."""

    def generate(self, request: ProviderRequest, timeout_seconds: float) -> ProviderResponse: ...


@dataclass(frozen=True)
class RedactionReport:
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.counts.values())


class Redactor(Protocol):
    """Removes secrets and personal data from text before it leaves the platform. The real
    implementation arrives in Stage 11 Step 3; the gateway cannot be built without one."""

    def redact(self, text: str) -> tuple[str, RedactionReport]: ...


@dataclass(frozen=True)
class CallContext:
    """Who a call is for. ``agent_run_id`` ties usage to a workflow run (per-run budgets)."""

    project_id: uuid.UUID | None
    requested_by: uuid.UUID | None
    agent_run_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None
    request: RequestContext | None = None


@dataclass(frozen=True)
class GatewayRequest:
    purpose: str
    template_version: str
    system: str
    prompt: str
    output_schema: type[BaseModel]
    max_output_tokens: int | None = None


@dataclass(frozen=True)
class GatewayResult:
    output: BaseModel
    usage_id: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    latency_ms: int
    attempts: int
    prompt_hash: str
    redactions: dict[str, int] = field(default_factory=dict)  # kind -> count, never values
