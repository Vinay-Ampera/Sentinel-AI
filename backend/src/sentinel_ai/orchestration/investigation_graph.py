"""Investigation graph (Stage 11): ranked, evidence-cited hypotheses for a failure.

    load_subject -> classify -> decide_llm -> llm_analyse -> validate

The failure class comes from code. Infrastructure, timeout, missing-dependency and similar
classes are explained deterministically and never reach a model. For the rest the model may
add hypotheses that cite evidence it was shown; every output carries the standing limitation
that nothing was re-run. A model failure leaves the deterministic classification in place."""

import hashlib
import uuid
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from sentinel_ai.agents import investigation as agent
from sentinel_ai.core.errors import DomainError
from sentinel_ai.integrations.llm import evidence_filter as ef
from sentinel_ai.orchestration.common import WorkflowDeps, cached_output, call_model
from sentinel_ai.repositories import agent_context
from sentinel_ai.repositories import findings as findings_repo
from sentinel_ai.repositories import observability as obs_repo
from sentinel_ai.services import agent_evidence


class InvestigationState(TypedDict, total=False):
    items: list[ef.Excerpt]
    classification: str
    input_hash: str
    degraded_reason: str | None
    used_llm: bool
    cache_hit: bool
    result: dict[str, Any]


def collect_subject(
    deps: WorkflowDeps,
    result_id: uuid.UUID | None,
    finding_id: uuid.UUID | None,
    alert_id: uuid.UUID | None = None,
) -> tuple[list[ef.Excerpt], list[str], str, bool, list[str], bool]:
    """(excerpts, failure messages, status, is_finding, notes, from_reported_events).
    Always project-scoped. An alert contributes its reported events, or (when it points at
    a result or a finding) the same evidence a person would open from there."""
    items: list[ef.Excerpt] = []
    messages: list[str] = []
    notes: list[str] = []
    status = "failed"
    from_events = False
    if alert_id is not None:
        alert = obs_repo.get_alert(deps.db, deps.project_id, alert_id)
        if alert is None:
            raise DomainError(404, "not_found", "Alert not found")
        if alert["group_id"] is not None:
            more_items, msgs = agent_evidence.alert_excerpts(deps.db, deps.project_id, alert)
            items += more_items
            messages += msgs
            from_events = True
        result_id = alert["result_id"] if not from_events else result_id
        finding_id = alert["finding_id"] if not from_events else finding_id
    scoped_result_id = result_id
    is_finding = finding_id is not None
    if finding_id is not None:
        finding = findings_repo.get_finding(deps.db, finding_id)
        if finding is None or finding.project_id != deps.project_id:
            raise DomainError(404, "not_found", "Finding not found")
        items.append(agent_evidence.finding_excerpt(finding))
        events = agent_evidence.finding_events_excerpt(deps.db, finding)
        if events is not None:
            items.append(events)
        scoped_result_id = finding.result_id if scoped_result_id is None else scoped_result_id
    if scoped_result_id is not None:
        scoped = agent_context.get_result_scoped(deps.db, deps.project_id, scoped_result_id)
        if scoped is None:
            if result_id is not None:
                raise DomainError(404, "not_found", "Result not found")
        else:
            more, msgs, more_notes = agent_evidence.result_excerpts(
                deps.db, deps.ctx, deps.user, deps.settings, scoped
            )
            items += more
            messages += msgs
            notes += more_notes
            status = scoped.result.status
    return items, messages, status, is_finding, notes, from_events


def content_hash(items: list[ef.Excerpt], status: str) -> str:
    return hashlib.sha256(
        ("\x1e".join(f"{i.id}\x1f{i.text}" for i in items) + status).encode()
    ).hexdigest()


def build_investigation_graph(
    deps: WorkflowDeps,
    result_id: uuid.UUID | None,
    finding_id: uuid.UUID | None,
    alert_id: uuid.UUID | None = None,
) -> Any:
    trace = deps.trace

    def load_subject(state: InvestigationState) -> InvestigationState:
        items, messages, status, is_finding, notes, from_events = collect_subject(
            deps, result_id, finding_id, alert_id
        )
        deps.db.commit()  # evidence reads are audited; end the transaction before any model call
        subject = (
            f"alert:{alert_id}" if alert_id else f"finding:{finding_id}" if finding_id
            else f"result:{result_id}"
        )  # fmt: skip
        trace.step("load_subject", "deterministic", "ok", {"excerpts": len(items), "notes": notes})
        if alert_id is not None and (from_events or not (items or is_finding)):
            cls, why = agent.classify_alert(from_events)
        else:
            cls, why = agent.classify(status, messages, is_finding=is_finding)
        trace.step("classify", "deterministic", cls, {"status": status})
        return {
            "items": items,
            "classification": cls,
            "input_hash": agent.input_hash(
                subject, content_hash(items, status), deps.settings.gemini_model
            ),
            "result": {
                "classification": cls,
                "explanation": why,
                "limitations": agent.LIMITATIONS,
                "causes": [],
            },
        }

    def after_load(state: InvestigationState) -> str:
        return "decide_llm" if state["classification"] in agent.MODEL_CLASSES else "end"

    def decide_llm(state: InvestigationState) -> InvestigationState:
        if not deps.gateway.enabled:
            trace.step("decide_llm", "decision", "llm_disabled", {})
            return {"degraded_reason": "llm_disabled"}
        cached = cached_output(deps, "investigation", state["input_hash"])
        if cached is not None:
            trace.step("decide_llm", "decision", "cache_hit", {})
            return {
                "cache_hit": True,
                "result": {**state["result"], "causes": cached.get("causes", []), "output": cached},
            }
        trace.step("decide_llm", "decision", "call_model", {"class": state["classification"]})
        return {}

    def after_decide(state: InvestigationState) -> str:
        return "end" if state.get("degraded_reason") or state.get("cache_hit") else "llm_analyse"

    def llm_analyse(state: InvestigationState) -> InvestigationState:
        request, block = agent.build_request(state["items"], state["classification"])
        call = call_model(deps, "llm_analyse", request, block)
        if call.result is None:
            return {"degraded_reason": call.reason, "used_llm": call.used}
        out = call.result.output
        assert isinstance(out, agent.InvestigationOut)
        causes, dropped = agent.validate(out, set(block.included_ids))
        if out.causes and not causes:
            trace.step("validate", "policy", "invalid_output", {"dropped": dropped})
            return {"degraded_reason": "invalid_output", "used_llm": True}
        trace.step("validate", "policy", "ok", {"causes": len(causes), "dropped": dropped})
        message = None if causes else "The evidence does not support a specific cause."
        return {
            "used_llm": True,
            "result": {
                **state["result"],
                "causes": causes,
                "dropped": dropped,
                "output": {"causes": causes},
                "message": message,
            },
        }

    g: Any = StateGraph(InvestigationState)
    g.add_node("load_subject", load_subject)
    g.add_node("decide_llm", decide_llm)
    g.add_node("llm_analyse", llm_analyse)
    g.set_entry_point("load_subject")
    g.add_conditional_edges("load_subject", after_load, {"decide_llm": "decide_llm", "end": END})
    g.add_conditional_edges("decide_llm", after_decide, {"llm_analyse": "llm_analyse", "end": END})
    g.add_edge("llm_analyse", END)
    return g.compile()
