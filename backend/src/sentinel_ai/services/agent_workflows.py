"""Entry points for agent workflows (Stage 11): run record, graph, audit.

Callers (routes) have already checked the role capability and project access level; the graphs
re-check access right before they write. A workflow always ends in a recorded state:
``succeeded``, ``degraded`` (the model part was unavailable, blocked or invalid; the reason is
stable and the deterministic part of the result is kept) or ``failed`` (an error, or the
process died and the sweep closed it).
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from sentinel_ai.agents import analysis as analysis_agent
from sentinel_ai.agents import investigation as investigation_agent
from sentinel_ai.agents import planning as planning_agent
from sentinel_ai.agents import regression as regression_agent
from sentinel_ai.agents import verification as verification_agent
from sentinel_ai.core.config import Settings
from sentinel_ai.core.errors import DomainError
from sentinel_ai.integrations.llm.gateway import LLMGateway
from sentinel_ai.orchestration import (
    analysis_graph,
    investigation_graph,
    planning_graph,
    regression_graph,
    verification_graph,
)
from sentinel_ai.orchestration.common import RECURSION_LIMIT, WorkflowDeps
from sentinel_ai.orchestration.trace import Trace
from sentinel_ai.repositories import agent_runs
from sentinel_ai.repositories.agent_runs import AgentRunRecord, AgentStepRecord
from sentinel_ai.repositories.identity import UserRecord
from sentinel_ai.services import audit
from sentinel_ai.services.audit import RequestContext

STALE_AFTER_FACTOR = 2.0  # a run is "interrupted" after twice the workflow deadline


@dataclass(frozen=True)
class AgentRunDetail:
    run: AgentRunRecord
    steps: list[AgentStepRecord]


@dataclass(frozen=True)
class Runtime:
    """What every workflow needs from the application."""

    gateway: LLMGateway
    session_factory: sessionmaker[Session]
    settings: Settings


def sweep_interrupted(session_factory: sessionmaker[Session], settings: Settings) -> int:
    """Close runs and model reservations orphaned by a dead process (Q109)."""
    with session_factory() as db:
        closed = agent_runs.close_interrupted(
            db, settings.llm_graph_deadline_seconds * STALE_AFTER_FACTOR
        )
        db.commit()
    return closed


def _planning_result(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "plan_id": state.get("plan_id"),
        "check_ids": state.get("check_ids", []),
        "source": state.get("source") or None,
        "reasons": state.get("reasons", {}),
        "rejected": state.get("rejected", []),
        "message": state.get("message"),
    }


def _generic_result(state: dict[str, Any]) -> dict[str, Any]:
    return dict(state.get("result") or {})


def _execute(
    db: Session,
    ctx: RequestContext,
    user: UserRecord,
    project_id: uuid.UUID,
    rt: Runtime,
    *,
    workflow: str,
    template_version: str,
    subject: tuple[str, uuid.UUID] | None,
    build: Callable[[uuid.UUID, Trace], Any],
    make_result: Callable[[dict[str, Any]], dict[str, Any]],
) -> AgentRunDetail:
    sweep_interrupted(rt.session_factory, rt.settings)
    with rt.session_factory() as s:
        run_id = agent_runs.create_run(
            s, project_id=project_id, workflow=workflow, requested_by=user.id,
            subject_type=subject[0] if subject else None,
            subject_id=subject[1] if subject else None,
        )  # fmt: skip
        s.commit()
    trace = Trace(rt.session_factory, run_id)
    state: dict[str, Any] = {}
    try:
        graph = build(run_id, trace)
        state = graph.invoke({}, {"recursion_limit": RECURSION_LIMIT})
    except DomainError as exc:  # archived project, lost access, bad subject: not a model matter
        db.rollback()
        _finish(rt, run_id, "failed", None, state, make_result, template_version, error=exc.code)
        trace.step("error", "decision", exc.code, {})
        _audit(db, ctx, user, project_id, run_id, workflow, "failed", None)
        db.commit()
        raise
    except Exception:
        db.rollback()
        _finish(
            rt, run_id, "failed", None, state, make_result, template_version,
            error="internal_error",
        )  # fmt: skip
        trace.step("error", "decision", "internal_error", {})
        raise

    reason = state.get("degraded_reason")
    status = "degraded" if reason else "succeeded"
    _finish(rt, run_id, status, reason, state, make_result, template_version)
    _audit(db, ctx, user, project_id, run_id, workflow, status, reason)
    db.commit()
    with rt.session_factory() as s:
        run = agent_runs.get_run(s, project_id, run_id)
        steps = agent_runs.list_steps(s, run_id)
    assert run is not None
    return AgentRunDetail(run, steps)


def _finish(
    rt: Runtime,
    run_id: uuid.UUID,
    status: str,
    reason: str | None,
    state: dict[str, Any],
    make_result: Callable[[dict[str, Any]], dict[str, Any]],
    template_version: str,
    *,
    error: str | None = None,
) -> None:
    result = make_result(state)
    if error:
        result["error"] = error
    used = bool(state.get("used_llm"))
    with rt.session_factory() as s:
        agent_runs.finish_run(
            s, run_id, status=status, degraded_reason=reason, used_llm=used,
            cache_hit=bool(state.get("cache_hit")),
            model=rt.settings.gemini_model if used else None,
            input_hash=state.get("input_hash"), template_version=template_version, result=result,
        )  # fmt: skip
        s.commit()


def _audit(
    db: Session,
    ctx: RequestContext,
    user: UserRecord,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    workflow: str,
    status: str,
    reason: str | None,
) -> None:
    audit.record(
        db, ctx, action=f"agent_run.{workflow}",
        outcome="success" if status == "succeeded" else "failure",
        actor_user_id=user.id, project_id=project_id, target_type="agent_run",
        target_id=str(run_id), detail={"status": status, "degraded_reason": reason},
    )  # fmt: skip


def _deps(
    db: Session, ctx: RequestContext, user: UserRecord, project_id: uuid.UUID,
    rt: Runtime, run_id: uuid.UUID, trace: Trace,
) -> WorkflowDeps:  # fmt: skip
    return WorkflowDeps(
        db=db, ctx=ctx, user=user, project_id=project_id, run_id=run_id, gateway=rt.gateway,
        deadline=rt.gateway.new_deadline(rt.settings.llm_graph_deadline_seconds),
        settings=rt.settings, trace=trace, session_factory=rt.session_factory,
    )  # fmt: skip


# ---- workflows ------------------------------------------------------------------------------


def run_planning(
    db: Session,
    ctx: RequestContext,
    user: UserRecord,
    project_id: uuid.UUID,
    *,
    prompt: str,
    snapshot_id: uuid.UUID | None,
    rt: Runtime,
) -> AgentRunDetail:
    text = prompt.strip()
    if not text:
        raise DomainError(422, "validation_failed", "prompt must not be blank")
    if len(text) > planning_agent.MAX_REQUEST_CHARS:
        raise DomainError(
            422, "validation_failed",
            f"prompt must be at most {planning_agent.MAX_REQUEST_CHARS} characters",
        )  # fmt: skip

    def build(run_id: uuid.UUID, trace: Trace) -> Any:
        deps = planning_graph.PlanningDeps(
            db=db, ctx=ctx, user=user, project_id=project_id, run_id=run_id, prompt=text,
            snapshot_id=snapshot_id, gateway=rt.gateway,
            deadline=rt.gateway.new_deadline(rt.settings.llm_graph_deadline_seconds),
            settings=rt.settings, trace=trace, session_factory=rt.session_factory,
        )  # fmt: skip
        return planning_graph.build_planning_graph(deps)

    return _execute(
        db, ctx, user, project_id, rt, workflow="planning",
        template_version=planning_agent.TEMPLATE_VERSION,
        subject=("snapshot", snapshot_id) if snapshot_id else None,
        build=build, make_result=_planning_result,
    )  # fmt: skip


def run_analysis(
    db: Session, ctx: RequestContext, user: UserRecord, project_id: uuid.UUID,
    *, snapshot_id: uuid.UUID, rt: Runtime,
) -> AgentRunDetail:  # fmt: skip
    return _execute(
        db, ctx, user, project_id, rt, workflow="analysis",
        template_version=analysis_agent.TEMPLATE_VERSION, subject=("snapshot", snapshot_id),
        build=lambda rid, tr: analysis_graph.build_analysis_graph(
            _deps(db, ctx, user, project_id, rt, rid, tr), snapshot_id
        ),
        make_result=_generic_result,
    )  # fmt: skip


def run_investigation(
    db: Session, ctx: RequestContext, user: UserRecord, project_id: uuid.UUID,
    *, result_id: uuid.UUID | None, finding_id: uuid.UUID | None, rt: Runtime,
) -> AgentRunDetail:  # fmt: skip
    subject = ("finding", finding_id) if finding_id else ("result", result_id)
    assert subject[1] is not None
    return _execute(
        db, ctx, user, project_id, rt, workflow="investigation",
        template_version=investigation_agent.TEMPLATE_VERSION, subject=(subject[0], subject[1]),
        build=lambda rid, tr: investigation_graph.build_investigation_graph(
            _deps(db, ctx, user, project_id, rt, rid, tr), result_id, finding_id
        ),
        make_result=_generic_result,
    )  # fmt: skip


def run_regression(
    db: Session, ctx: RequestContext, user: UserRecord, project_id: uuid.UUID,
    *, result_id: uuid.UUID | None, finding_id: uuid.UUID | None, rt: Runtime,
) -> AgentRunDetail:  # fmt: skip
    subject = ("finding", finding_id) if finding_id else ("result", result_id)
    assert subject[1] is not None
    return _execute(
        db, ctx, user, project_id, rt, workflow="regression",
        template_version=regression_agent.TEMPLATE_VERSION, subject=(subject[0], subject[1]),
        build=lambda rid, tr: regression_graph.build_regression_graph(
            _deps(db, ctx, user, project_id, rt, rid, tr), result_id, finding_id
        ),
        make_result=_generic_result,
    )  # fmt: skip


def run_verification(
    db: Session, ctx: RequestContext, user: UserRecord, project_id: uuid.UUID,
    *, finding_id: uuid.UUID, mode: str, run_id: uuid.UUID | None, summarize: bool, rt: Runtime,
) -> AgentRunDetail:  # fmt: skip
    def build(rid: uuid.UUID, tr: Trace) -> Any:
        deps = _deps(db, ctx, user, project_id, rt, rid, tr)
        if mode == "prepare":
            return verification_graph.build_prepare_graph(deps, finding_id)
        assert run_id is not None
        return verification_graph.build_conclude_graph(deps, finding_id, run_id, summarize)

    return _execute(
        db, ctx, user, project_id, rt, workflow="verification",
        template_version=verification_agent.TEMPLATE_VERSION, subject=("finding", finding_id),
        build=build, make_result=lambda s: {**_generic_result(s), "mode": mode},
    )  # fmt: skip


def list_runs(db: Session, project_id: uuid.UUID, limit: int) -> list[AgentRunRecord]:
    return agent_runs.list_runs(db, project_id, limit)


def get_run(db: Session, project_id: uuid.UUID, run_id: uuid.UUID) -> AgentRunDetail:
    run = agent_runs.get_run(db, project_id, run_id)  # scoped by project: an id alone is nothing
    if run is None:
        raise DomainError(404, "not_found", "Agent run not found")
    return AgentRunDetail(run, agent_runs.list_steps(db, run_id))
