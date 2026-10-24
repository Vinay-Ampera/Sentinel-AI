"""Analysis graph (Stage 11): optional interpretation of a deterministic project analysis.

    load_snapshot -> decide_llm -> llm_interpret -> validate

The deterministic analysis (facts, inferences, gaps) is untouched and is returned beside the
interpretation. The model runs only because someone asked for this workflow; it is skipped
when the analysis has no facts, served from cache when the same snapshot was interpreted
before, and its claims are kept only if they cite evidence it was shown."""

import uuid
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from sentinel_ai.agents import analysis as agent
from sentinel_ai.core.errors import DomainError
from sentinel_ai.orchestration.common import WorkflowDeps, cached_output, call_model
from sentinel_ai.repositories import projects


class AnalysisState(TypedDict, total=False):
    detected: dict[str, Any]
    input_hash: str
    degraded_reason: str | None
    used_llm: bool
    cache_hit: bool
    result: dict[str, Any]


def build_analysis_graph(deps: WorkflowDeps, snapshot_id: uuid.UUID) -> Any:
    trace = deps.trace

    def load_snapshot(state: AnalysisState) -> AnalysisState:
        snap = projects.get_snapshot(deps.db, snapshot_id)
        if snap is None or snap.project_id != deps.project_id:  # other project: same 404
            raise DomainError(404, "not_found", "Analysis snapshot not found")
        if snap.status != "completed":
            raise DomainError(422, "snapshot_not_completed", "That analysis did not complete")
        deps.db.rollback()
        detected = snap.detected or {}
        counts = {
            "facts": len(detected.get("facts", {})),
            "inferences": len(detected.get("inferences", [])),
            "gaps": len(detected.get("gaps", [])),
        }
        trace.step("load_snapshot", "deterministic", "ok", counts)
        digest = agent.input_hash(snap.content_sha256, str(snap.id), deps.settings.gemini_model)
        base = {"deterministic": {"snapshot_id": str(snap.id), **counts}}
        if not counts["facts"]:
            return {
                "result": {**base, "message": "The analysis has no facts to interpret."},
                "input_hash": digest,
            }
        return {"detected": detected, "input_hash": digest, "result": base}

    def after_load(state: AnalysisState) -> str:
        return "decide_llm" if state.get("detected") else "end"

    def decide_llm(state: AnalysisState) -> AnalysisState:
        if not deps.gateway.enabled:
            trace.step("decide_llm", "decision", "llm_disabled", {})
            return {"degraded_reason": "llm_disabled"}
        cached = cached_output(deps, "analysis", state["input_hash"])
        if cached is not None:
            trace.step("decide_llm", "decision", "cache_hit", {})
            return {
                "cache_hit": True,
                "result": {**state["result"], "output": cached, "dropped": 0},
            }
        trace.step("decide_llm", "decision", "call_model", {"reason": "interpretation requested"})
        return {}

    def after_decide(state: AnalysisState) -> str:
        return "end" if state.get("degraded_reason") or state.get("cache_hit") else "llm_interpret"

    def llm_interpret(state: AnalysisState) -> AnalysisState:
        request, block = agent.build_request(state["detected"])
        call = call_model(deps, "llm_interpret", request, block)
        if call.result is None:
            return {"degraded_reason": call.reason, "used_llm": call.used}
        out = call.result.output
        assert isinstance(out, agent.AnalysisInterpretation)
        clean, dropped = agent.validate(out, set(block.included_ids))
        if clean is None:
            trace.step(
                "validate", "policy", "invalid_output", {"why": "summary cites no shown evidence"}
            )
            return {"degraded_reason": "invalid_output", "used_llm": True}
        trace.step("validate", "policy", "ok", {"dropped_claims": dropped})
        return {
            "used_llm": True,
            "result": {**state["result"], "output": clean, "dropped": dropped},
        }

    g: Any = StateGraph(AnalysisState)
    g.add_node("load_snapshot", load_snapshot)
    g.add_node("decide_llm", decide_llm)
    g.add_node("llm_interpret", llm_interpret)
    g.set_entry_point("load_snapshot")
    g.add_conditional_edges("load_snapshot", after_load, {"decide_llm": "decide_llm", "end": END})
    g.add_conditional_edges(
        "decide_llm", after_decide, {"llm_interpret": "llm_interpret", "end": END}
    )
    g.add_edge("llm_interpret", END)
    return g.compile()
