"""Verification graphs (Stage 11): prepare a re-scan, then conclude it.

prepare:  load_finding -> store_draft_plan          (deterministic; no model)
conclude: load_outcome -> decide_llm -> llm_summarize -> validate

Neither graph changes a finding. ``prepare`` drafts a normal catalog plan for the finding's own
scanner that a person must submit and have approved before it can run. ``conclude`` compares
what the existing re-scan logic recorded (``verification_attempts``) with the run's result and
reports a verdict computed by code; a model, only if asked, words a summary with limitations.
Verification state and status stay with ``services/findings``."""

import hashlib
import uuid
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from sentinel_ai.agents import verification as agent
from sentinel_ai.core.errors import DomainError
from sentinel_ai.integrations.llm import evidence_filter as ef
from sentinel_ai.orchestration.common import WorkflowDeps, call_model, recheck_run_access
from sentinel_ai.repositories import agent_context
from sentinel_ai.repositories import findings as findings_repo
from sentinel_ai.repositories.findings import FindingRecord
from sentinel_ai.repositories.runs import TERMINAL
from sentinel_ai.services import agent_evidence
from sentinel_ai.services import plans as plans_service
from sentinel_ai.services.check_catalog import from_check_ids

STANDARD_LIMITATIONS = [
    "Absence from a static scan does not prove the weakness is gone.",
    "Dynamic (ZAP) scans never verify a finding automatically.",
    "This workflow never changes a finding's status; a person decides.",
]


class VerificationState(TypedDict, total=False):
    finding: FindingRecord
    check_id: str
    items: list[ef.Excerpt]
    input_hash: str
    degraded_reason: str | None
    used_llm: bool
    cache_hit: bool
    result: dict[str, Any]


def _load_finding(deps: WorkflowDeps, finding_id: uuid.UUID) -> FindingRecord:
    finding = findings_repo.get_finding(deps.db, finding_id)
    if finding is None or finding.project_id != deps.project_id:
        raise DomainError(404, "not_found", "Finding not found")
    return finding


def ineligible_reason(finding: FindingRecord) -> str | None:
    if finding.status in agent.NO_REVERIFY:
        return f"A finding marked '{finding.status}' is not re-verified."
    if finding.detected_by not in agent.TOOL_CHECK:
        return (
            f"'{finding.detected_by}' findings cannot be verified by a re-scan; re-test manually."
        )
    if finding.source_id is None:
        return "The finding has no recorded source to re-scan."
    return None


def build_prepare_graph(deps: WorkflowDeps, finding_id: uuid.UUID) -> Any:
    trace = deps.trace

    def load_finding(state: VerificationState) -> VerificationState:
        finding = _load_finding(deps, finding_id)
        deps.db.rollback()
        reason = ineligible_reason(finding)
        if reason is None:
            check_id = agent.TOOL_CHECK[finding.detected_by]
            ctx, _ = plans_service.planning_context(deps.db, deps.project_id, None, lock=False)
            deps.db.rollback()
            props = from_check_ids(ctx, {check_id: "re-scan"}, origin_note="x")
            if not any(p.source_id == finding.source_id for p in props):
                reason = "The finding's source is not the project's current analysed source."
        trace.step(
            "load_finding",
            "deterministic",
            "eligible" if reason is None else "not_eligible",
            {"tool": finding.detected_by, "status": finding.status},
        )
        if reason is not None:
            return {"result": {"eligible": False, "reason": reason, "plan_id": None}}
        return {
            "finding": finding,
            "check_id": agent.TOOL_CHECK[finding.detected_by],
            "result": {"eligible": True, "reason": None, "plan_id": None},
        }

    def after_load(state: VerificationState) -> str:
        return "store_draft_plan" if state["result"]["eligible"] else "end"

    def store_draft_plan(state: VerificationState) -> VerificationState:
        recheck_run_access(deps)
        finding, check_id = state["finding"], state["check_id"]
        ctx, notes = plans_service.planning_context(deps.db, deps.project_id, None, lock=True)
        props = [
            p
            for p in from_check_ids(
                ctx,
                {check_id: f"Re-scan to verify finding {agent_evidence.short(finding.id)}"},
                origin_note="Verification",
            )
            if p.source_id == finding.source_id
        ]
        if not props:
            deps.db.rollback()
            trace.step("store_draft_plan", "policy", "no_proposals", {})
            return {
                "result": {
                    "eligible": False,
                    "plan_id": None,
                    "reason": "The finding's source is no longer the analysed source.",
                }
            }
        detail = plans_service.store_plan(
            deps.db,
            deps.ctx,
            deps.user,
            deps.project_id,
            plan_ctx=ctx,
            notes=notes,
            mode="prompt_based",
            prompt=f"Verify finding {agent_evidence.short(finding.id)}",
            proposals=props,
            audit_detail={
                "agent_run_id": str(deps.run_id),
                "source": "verification",
                "finding_id": str(finding.id),
            },
        )
        deps.db.commit()
        trace.step(
            "store_draft_plan",
            "policy",
            "draft_created",
            {"plan_id": str(detail.plan.id), "check_id": check_id},
        )
        return {
            "result": {
                "eligible": True,
                "reason": None,
                "plan_id": str(detail.plan.id),
                "check_id": check_id,
                "next_steps": [
                    "Submit the draft plan",
                    "Have it approved",
                    "Run it",
                    "Conclude verification with that run's id",
                ],
            }
        }

    g: Any = StateGraph(VerificationState)
    g.add_node("load_finding", load_finding)
    g.add_node("store_draft_plan", store_draft_plan)
    g.set_entry_point("load_finding")
    g.add_conditional_edges(
        "load_finding", after_load, {"store_draft_plan": "store_draft_plan", "end": END}
    )
    g.add_edge("store_draft_plan", END)
    return g.compile()


def build_conclude_graph(
    deps: WorkflowDeps, finding_id: uuid.UUID, run_id: uuid.UUID, summarize: bool
) -> Any:
    trace = deps.trace

    def load_outcome(state: VerificationState) -> VerificationState:
        finding = _load_finding(deps, finding_id)
        status = agent_context.run_in_project(deps.db, deps.project_id, run_id)
        if status is None:
            raise DomainError(404, "not_found", "Run not found")
        if status not in TERMINAL:
            raise DomainError(409, "run_not_finished", "That run has not finished yet")
        check_id = agent.TOOL_CHECK.get(finding.detected_by)
        result_status = (
            agent_context.result_for_check(deps.db, run_id, check_id) if check_id else None
        )
        attempts = [
            a for a in findings_repo.list_attempts(deps.db, finding.id) if a.run_id == run_id
        ]
        attempt = attempts[-1].outcome if attempts else None
        verdict, reason = agent.compare(
            finding_status=finding.status,
            last_run_id=str(finding.last_run_id) if finding.last_run_id else None,
            run_id=str(run_id),
            attempt_outcome=attempt,
            result_status=result_status,
        )
        items = [agent_evidence.finding_excerpt(finding)]
        summary = (
            f"verdict: {verdict}\nreason: {reason}\nre-scan result status: {result_status}\n"
            f"verification attempt for this run: {attempt}\n"
            f"finding status: {finding.status}\nverification state: {finding.verification_state}"
        )
        items.append(
            ef.Excerpt(
                f"scan_summary:run_{agent_evidence.short(run_id)}",
                "scan_summary",
                summary,
                priority=9,
            )
        )
        events = agent_evidence.finding_events_excerpt(deps.db, finding)
        if events is not None:
            items.append(events)
        deps.db.rollback()
        trace.step(
            "compare",
            "deterministic",
            verdict,
            {"result_status": result_status, "attempt": attempt},
        )
        digest = agent.input_hash(
            str(finding.id),
            str(run_id),
            hashlib.sha256(summary.encode()).hexdigest(),
            deps.settings.gemini_model,
        )
        return {
            "items": items,
            "input_hash": digest,
            "finding": finding,
            "result": {
                "verdict": verdict,
                "reason": reason,
                "finding_status": finding.status,
                "verification_state": finding.verification_state,
                "result_status": result_status,
                "limitations": STANDARD_LIMITATIONS,
            },
        }

    def after_load(state: VerificationState) -> str:
        return "decide_llm" if summarize else "end"

    def decide_llm(state: VerificationState) -> VerificationState:
        if not deps.gateway.enabled:
            trace.step("decide_llm", "decision", "llm_disabled", {})
            return {"degraded_reason": "llm_disabled"}
        trace.step("decide_llm", "decision", "call_model", {"reason": "summary requested"})
        return {}

    def after_decide(state: VerificationState) -> str:
        return "end" if state.get("degraded_reason") else "llm_summarize"

    def llm_summarize(state: VerificationState) -> VerificationState:
        request, block = agent.build_request(state["items"], state["result"]["verdict"])
        call = call_model(deps, "llm_summarize", request, block)
        if call.result is None:
            return {"degraded_reason": call.reason, "used_llm": call.used}
        out = call.result.output
        assert isinstance(out, agent.VerificationSummary)
        clean = agent.validate(out, set(block.included_ids))
        if clean is None:
            trace.step("validate", "policy", "invalid_output", {})
            return {"degraded_reason": "invalid_output", "used_llm": True}
        trace.step("validate", "policy", "ok", {})
        return {"used_llm": True, "result": {**state["result"], "output": clean}}

    g: Any = StateGraph(VerificationState)
    g.add_node("load_outcome", load_outcome)
    g.add_node("decide_llm", decide_llm)
    g.add_node("llm_summarize", llm_summarize)
    g.set_entry_point("load_outcome")
    g.add_conditional_edges("load_outcome", after_load, {"decide_llm": "decide_llm", "end": END})
    g.add_conditional_edges(
        "decide_llm", after_decide, {"llm_summarize": "llm_summarize", "end": END}
    )
    g.add_edge("llm_summarize", END)
    return g.compile()
