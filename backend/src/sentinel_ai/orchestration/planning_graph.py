"""Planning graph (Stage 11, ADR-0010): free-text request -> draft test plan.

    deterministic_select --matched--> store_draft_plan
            |no match
         decide_llm --disabled / cache hit--> ...
            |call
        llm_propose -> validate_catalog -> store_draft_plan

Keyword selection runs first and the model is called only when it matched nothing. The model
can only name catalog check ids; ``store_draft_plan`` rebuilds the proposals from the catalog
(``from_check_ids``) against a fresh context, and ``plans.store_plan`` computes risk, approval
need and target gating exactly as for any other plan. The graph cannot submit or approve a
plan and imports nothing from execution, approvals or policy writers (a test enforces it).
"""

import uuid
from dataclasses import dataclass
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from sentinel_ai.agents import planning as agent
from sentinel_ai.core.config import Settings
from sentinel_ai.core.permissions import AccessLevel
from sentinel_ai.integrations.llm.deadline import Deadline
from sentinel_ai.integrations.llm.errors import LLMError
from sentinel_ai.integrations.llm.gateway import LLMGateway
from sentinel_ai.integrations.llm.types import CallContext
from sentinel_ai.orchestration.trace import Trace
from sentinel_ai.repositories import agent_runs
from sentinel_ai.repositories.identity import UserRecord
from sentinel_ai.services import plans as plans_service
from sentinel_ai.services import project_access
from sentinel_ai.services.audit import RequestContext
from sentinel_ai.services.check_catalog import from_check_ids, from_prompt, match_prompt

RECURSION_LIMIT = 12
CACHE_MAX_AGE_HOURS = 24


class PlanningState(TypedDict, total=False):
    source: str  # keywords | cache | model
    reasons: dict[str, str]  # validated check id -> reason (model / cache path)
    rejected: list[dict[str, Any]]
    degraded_reason: str | None
    used_llm: bool
    cache_hit: bool
    input_hash: str
    app_type: str
    plan_id: str | None
    check_ids: list[str]
    message: str | None
    proposal_empty: bool


@dataclass
class PlanningDeps:
    db: Session
    ctx: RequestContext
    user: UserRecord
    project_id: uuid.UUID
    run_id: uuid.UUID
    prompt: str
    snapshot_id: uuid.UUID | None
    gateway: LLMGateway
    deadline: Deadline
    settings: Settings
    trace: Trace
    session_factory: Any


def build_planning_graph(deps: PlanningDeps) -> Any:
    trace = deps.trace

    def deterministic_select(state: PlanningState) -> PlanningState:
        plan_ctx, _ = plans_service.planning_context(
            deps.db, deps.project_id, deps.snapshot_id, lock=False
        )
        deps.db.rollback()  # end the read transaction; nothing is held while a model runs
        hits = match_prompt(deps.prompt)
        digest = agent.input_hash(deps.prompt, plan_ctx, deps.settings.gemini_model)
        trace.step(
            "deterministic_select", "deterministic", "matched" if hits else "no_match",
            {"matched_checks": sorted(hits)},
        )  # fmt: skip
        return {
            "source": "keywords" if hits else "",
            "input_hash": digest,
            "app_type": plan_ctx.application_type,
        }

    def after_select(state: PlanningState) -> str:
        return "store_draft_plan" if state["source"] == "keywords" else "decide_llm"

    def decide_llm(state: PlanningState) -> PlanningState:
        if not deps.gateway.enabled:
            trace.step("decide_llm", "decision", "llm_disabled", {"reason": "no model configured"})
            return {"degraded_reason": "llm_disabled"}
        with deps.session_factory() as db:
            cached = agent_runs.find_cached_result(
                db, deps.project_id, "planning", state["input_hash"], CACHE_MAX_AGE_HOURS
            )
        reasons = (cached or {}).get("reasons")
        if isinstance(reasons, dict) and reasons:
            trace.step("decide_llm", "decision", "cache_hit", {"checks": len(reasons)})
            return {"source": "cache", "reasons": {str(k): str(v) for k, v in reasons.items()},
                    "cache_hit": True}  # fmt: skip
        trace.step("decide_llm", "decision", "call_model", {"reason": "no keyword matched"})
        return {}

    def after_decide(state: PlanningState) -> str:
        if state.get("degraded_reason"):
            return "end"
        return "validate_catalog" if state.get("cache_hit") else "llm_propose"

    def llm_propose(state: PlanningState) -> PlanningState:
        plan_ctx, _ = plans_service.planning_context(
            deps.db, deps.project_id, deps.snapshot_id, lock=False
        )
        deps.db.rollback()
        request, block = agent.build_request(deps.prompt, plan_ctx)
        call_ctx = CallContext(deps.project_id, deps.user.id, agent_run_id=deps.run_id,
                               request=deps.ctx)  # fmt: skip
        try:
            result = deps.gateway.call(call_ctx, request, deps.deadline)
        except LLMError as exc:
            trace.step(
                "llm_propose", "llm", exc.reason,
                {"evidence": block.summary(), "redactions": exc.redactions,
                 "attempts": exc.attempts},
                usage_id=exc.usage_id,
            )  # fmt: skip
            return {"degraded_reason": exc.reason, "used_llm": exc.usage_id is not None}
        proposal = result.output
        assert isinstance(proposal, agent.PlanProposal)
        kept, rejected = agent.validate_choices(proposal, plan_ctx.application_type)
        trace.step(
            "llm_propose", "llm", "ok",
            {"evidence": block.summary(), "redactions": result.redactions,
             "attempts": result.attempts, "input_tokens": result.input_tokens,
             "output_tokens": result.output_tokens, "latency_ms": result.latency_ms,
             "proposed": len(proposal.checks)},
            usage_id=result.usage_id,
        )  # fmt: skip
        return {"source": "model", "reasons": kept, "rejected": rejected, "used_llm": True,
                "proposal_empty": not proposal.checks}  # fmt: skip

    def after_propose(state: PlanningState) -> str:
        return "end" if state.get("degraded_reason") else "validate_catalog"

    def validate_catalog(state: PlanningState) -> PlanningState:
        reasons = state.get("reasons", {})
        offered = set(agent.selectable_checks(state["app_type"]))
        reasons = {k: v for k, v in reasons.items() if k in offered}  # also re-checks cache hits
        rejected = state.get("rejected", [])
        if reasons:
            trace.step("validate_catalog", "policy", "ok",
                       {"accepted": sorted(reasons), "rejected": len(rejected)})  # fmt: skip
            return {"reasons": reasons}
        if state.get("proposal_empty"):
            trace.step("validate_catalog", "policy", "nothing_fits", {})
            return {"reasons": {}, "message": "No catalog check fits that request."}
        trace.step("validate_catalog", "policy", "invalid_output", {"rejected": len(rejected)})
        return {"reasons": {}, "degraded_reason": "invalid_output"}

    def after_validate(state: PlanningState) -> str:
        return "store_draft_plan" if state.get("reasons") else "end"

    def store_draft_plan(state: PlanningState) -> PlanningState:
        # The model may have run for seconds: re-check that the person can still plan here.
        project_access.require_project_access(deps.db, deps.user, deps.project_id, AccessLevel.RUN)
        plan_ctx, notes = plans_service.planning_context(
            deps.db, deps.project_id, deps.snapshot_id, lock=True
        )
        source = state["source"]
        if source == "keywords":
            proposals = from_prompt(plan_ctx, deps.prompt)
            note = "keywords"
        else:
            proposals = from_check_ids(
                plan_ctx, state["reasons"], origin_note="Proposed by the planning assistant"
            )
            note = source
        if not proposals:
            deps.db.rollback()
            trace.step("store_draft_plan", "policy", "no_proposals", {"source": note})
            return {"message": "No catalog check matched the request.", "check_ids": []}
        detail = plans_service.store_plan(
            deps.db, deps.ctx, deps.user, deps.project_id, plan_ctx=plan_ctx, notes=notes,
            mode="prompt_based", prompt=deps.prompt, proposals=proposals,
            audit_detail={"agent_run_id": str(deps.run_id), "source": note},
        )  # fmt: skip
        deps.db.commit()
        trace.step(
            "store_draft_plan", "policy", "draft_created",
            {"plan_id": str(detail.plan.id), "tests": len(detail.tests), "source": note,
             "plan_risk": detail.plan.risk_level},
        )  # fmt: skip
        ids = {str(t.definition.get("check_id", "")) for t in detail.tests} - {""}
        return {"plan_id": str(detail.plan.id), "check_ids": sorted(ids)}

    g: Any = StateGraph(PlanningState)
    g.add_node("deterministic_select", deterministic_select)
    g.add_node("decide_llm", decide_llm)
    g.add_node("llm_propose", llm_propose)
    g.add_node("validate_catalog", validate_catalog)
    g.add_node("store_draft_plan", store_draft_plan)
    g.set_entry_point("deterministic_select")
    g.add_conditional_edges(
        "deterministic_select",
        after_select,
        {"store_draft_plan": "store_draft_plan", "decide_llm": "decide_llm"},
    )
    g.add_conditional_edges(
        "decide_llm",
        after_decide,
        {"end": END, "validate_catalog": "validate_catalog", "llm_propose": "llm_propose"},
    )
    g.add_conditional_edges(
        "llm_propose", after_propose, {"validate_catalog": "validate_catalog", "end": END}
    )
    g.add_conditional_edges(
        "validate_catalog", after_validate, {"store_draft_plan": "store_draft_plan", "end": END}
    )
    g.add_edge("store_draft_plan", END)
    return g.compile()


__all__ = [
    "RECURSION_LIMIT",
    "PlanningDeps",
    "PlanningState",
    "build_planning_graph",
]
