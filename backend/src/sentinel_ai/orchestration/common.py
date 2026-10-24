"""Pieces every workflow graph shares (Stage 11): dependencies, model call + trace, cache."""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from sentinel_ai.core.config import Settings
from sentinel_ai.core.permissions import AccessLevel
from sentinel_ai.integrations.llm import evidence_filter as ef
from sentinel_ai.integrations.llm.deadline import Deadline
from sentinel_ai.integrations.llm.errors import LLMError
from sentinel_ai.integrations.llm.gateway import LLMGateway
from sentinel_ai.integrations.llm.types import CallContext, GatewayRequest, GatewayResult
from sentinel_ai.orchestration.trace import Trace
from sentinel_ai.repositories import agent_runs
from sentinel_ai.repositories.identity import UserRecord
from sentinel_ai.services import project_access
from sentinel_ai.services.audit import RequestContext

RECURSION_LIMIT = 12
CACHE_MAX_AGE_HOURS = 24


@dataclass
class WorkflowDeps:
    db: Session
    ctx: RequestContext
    user: UserRecord
    project_id: uuid.UUID
    run_id: uuid.UUID
    gateway: LLMGateway
    deadline: Deadline
    settings: Settings
    trace: Trace
    session_factory: Any


@dataclass
class ModelCall:
    result: GatewayResult | None
    reason: str | None  # stable degraded reason when result is None
    used: bool  # a usage row exists (the model may have been billed)


def call_model(
    deps: WorkflowDeps, node: str, request: GatewayRequest, block: ef.EvidenceBlock
) -> ModelCall:
    """One gateway call with its trace step. Failures are values, not exceptions: the graph
    decides how to degrade and keeps its deterministic result."""
    call_ctx = CallContext(
        deps.project_id, deps.user.id, agent_run_id=deps.run_id, request=deps.ctx
    )
    try:
        result = deps.gateway.call(call_ctx, request, deps.deadline)
    except LLMError as exc:
        deps.trace.step(
            node,
            "llm",
            exc.reason,
            {"evidence": block.summary(), "redactions": exc.redactions, "attempts": exc.attempts},
            usage_id=exc.usage_id,
        )
        return ModelCall(None, exc.reason, exc.usage_id is not None)
    deps.trace.step(
        node,
        "llm",
        "ok",
        {
            "evidence": block.summary(),
            "redactions": result.redactions,
            "attempts": result.attempts,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "latency_ms": result.latency_ms,
        },
        usage_id=result.usage_id,
    )
    return ModelCall(result, None, True)


def cached_output(deps: WorkflowDeps, workflow: str, input_hash: str) -> dict[str, Any] | None:
    """The validated output of an earlier identical, successful model run in this project."""
    with deps.session_factory() as db:
        found = agent_runs.find_cached_result(
            db, deps.project_id, workflow, input_hash, CACHE_MAX_AGE_HOURS
        )
    out = (found or {}).get("output")
    return out if isinstance(out, dict) and out else None


def recheck_run_access(deps: WorkflowDeps) -> None:
    """A model call can take seconds: confirm the person may still act before writing."""
    project_access.require_project_access(deps.db, deps.user, deps.project_id, AccessLevel.RUN)
