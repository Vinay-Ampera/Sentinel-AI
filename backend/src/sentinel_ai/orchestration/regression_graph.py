"""Regression-proposal graph (Stage 11): a drafted test for a reproducible failure.

    load_subject --not eligible--> end
        |eligible
    decide_llm -> llm_draft -> validate -> store_proposal

Eligibility is deterministic: a finding a person marked ``likely`` or ``confirmed``, or a
failed result with at least one failed case. The draft is checked by code (path rules, size,
parse-only syntax check, risk flags, name overlap) and stored as a *proposal* for review. It is
never written to the source tree, committed or run."""

import hashlib
import uuid
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from sentinel_ai.agents import regression as agent
from sentinel_ai.core.errors import DomainError
from sentinel_ai.integrations.llm import evidence_filter as ef
from sentinel_ai.orchestration.common import WorkflowDeps, call_model, recheck_run_access
from sentinel_ai.repositories import agent_context, projects
from sentinel_ai.repositories import findings as findings_repo
from sentinel_ai.repositories import observability as obs_repo
from sentinel_ai.repositories import regression_tests as proposals
from sentinel_ai.repositories import runs as runs_repo
from sentinel_ai.services import agent_evidence


class RegressionState(TypedDict, total=False):
    items: list[ef.Excerpt]
    frameworks: list[str]
    known_names: list[str]
    result_id: str | None
    finding_id: str | None
    alert_id: str | None
    group_id: str | None
    input_hash: str
    degraded_reason: str | None
    used_llm: bool
    cache_hit: bool
    result: dict[str, Any]
    draft: dict[str, Any]


def _analysis_hints(deps: WorkflowDeps) -> tuple[list[str], list[ef.Excerpt]]:
    snapshot = next(
        (
            s
            for s in projects.list_snapshots(deps.db, deps.project_id, 20)
            if s.status == "completed"
        ),
        None,
    )
    if snapshot is None:
        return [], []
    facts = (snapshot.detected or {}).get("facts", {})
    tools = [str(t.get("name")) for t in facts.get("test_tools", []) if isinstance(t, dict)]
    examples = (facts.get("test_files") or {}).get("examples", [])
    out = []
    if examples:
        text = "\n".join(str(e) for e in examples[:20])
        out.append(ef.Excerpt("existing_test:files", "existing_test", text, priority=3))
    return tools, out


def build_regression_graph(
    deps: WorkflowDeps,
    result_id: uuid.UUID | None,
    finding_id: uuid.UUID | None,
    alert_id: uuid.UUID | None = None,
) -> Any:
    trace = deps.trace

    def load_subject(state: RegressionState) -> RegressionState:
        finding = scoped = None
        rid = result_id
        alert = None
        group: dict[str, Any] | None = None
        if alert_id is not None:
            alert = obs_repo.get_alert(deps.db, deps.project_id, alert_id)
            if alert is None:
                raise DomainError(404, "not_found", "Alert not found")
            group = (
                obs_repo.get_group(deps.db, deps.project_id, alert["group_id"])
                if alert["group_id"]
                else None
            )
            rid = alert["result_id"]  # project-scoped below; may be None
        if finding_id is not None:
            finding = findings_repo.get_finding(deps.db, finding_id)
            if finding is None or finding.project_id != deps.project_id:
                raise DomainError(404, "not_found", "Finding not found")
            rid = rid or finding.result_id
        if rid is not None:
            scoped = agent_context.get_result_scoped(deps.db, deps.project_id, rid)
            if scoped is None and result_id is not None:
                raise DomainError(404, "not_found", "Result not found")

        items: list[ef.Excerpt] = []
        notes: list[str] = []
        known: list[str] = []
        failed_cases = 0
        if alert is not None and alert["group_id"] is not None:
            alert_items, _ = agent_evidence.alert_excerpts(deps.db, deps.project_id, alert)
            items += alert_items
        if finding is not None:
            items.append(agent_evidence.finding_excerpt(finding))
            events = agent_evidence.finding_events_excerpt(deps.db, finding)
            if events is not None:
                items.append(events)
        if scoped is not None:
            more, _, notes = agent_evidence.result_excerpts(
                deps.db, deps.ctx, deps.user, deps.settings, scoped
            )
            items += more
            cases = runs_repo.list_cases(deps.db, scoped.result.id, limit=500)
            known = [c.name for c in cases]
            failed_cases = sum(c.status in ("failed", "error") for c in cases)
        frameworks, hint_items = _analysis_hints(deps)
        items += hint_items
        deps.db.commit()  # evidence reads are audited; end the transaction before any model call

        if alert is not None:
            missing = agent.alert_missing_evidence(
                group,
                failed_result_case=bool(
                    scoped is not None
                    and scoped.result.status in agent.ELIGIBLE_RESULT_STATUSES
                    and failed_cases > 0
                ),
                frameworks=frameworks,
            )
            eligible = not missing
            why = "" if eligible else " ".join(missing)
        elif finding is not None:
            eligible = finding.verification_state in agent.ELIGIBLE_VERIFICATION_STATES
            why = (
                ""
                if eligible
                else (
                    f"The finding is '{finding.verification_state}'; a person must mark it "
                    "likely or confirmed first."
                )
            )
        else:
            ok = scoped is not None and scoped.result.status in agent.ELIGIBLE_RESULT_STATUSES
            eligible = ok and failed_cases > 0
            why = (
                ""
                if eligible
                else "Only a failed result with a failed test case can become a regression test."
            )
        trace.step("load_subject", "deterministic", "ok", {"excerpts": len(items), "notes": notes})
        subject = (
            f"alert:{alert_id}" if alert_id else f"finding:{finding_id}" if finding_id
            else f"result:{result_id}"
        )  # fmt: skip
        body = "\x1e".join(f"{i.id}\x1f{i.text}" for i in items)
        digest = agent.input_hash(
            subject, hashlib.sha256(body.encode()).hexdigest(), deps.settings.gemini_model
        )
        trace.step("check_eligibility", "decision", "eligible" if eligible else "not_eligible", {})
        out: RegressionState = {
            "items": items,
            "frameworks": frameworks,
            "known_names": known,
            "input_hash": digest,
            "result": {"eligible": eligible, "reason": why or None, "proposal_id": None},
            "result_id": str(scoped.result.id) if scoped and finding is None else None,
            "finding_id": str(finding.id) if finding else None,
            "alert_id": str(alert["id"]) if alert else None,
            "group_id": str(group["id"]) if group else None,
        }
        return out

    def after_load(state: RegressionState) -> str:
        return "decide_llm" if state["result"]["eligible"] else "end"

    def decide_llm(state: RegressionState) -> RegressionState:
        if not deps.gateway.enabled:
            trace.step("decide_llm", "decision", "llm_disabled", {})
            return {"degraded_reason": "llm_disabled"}
        existing = proposals.find_existing_for_input(deps.db, deps.project_id, state["input_hash"])
        deps.db.rollback()
        if existing is not None:
            trace.step("decide_llm", "decision", "reused_proposal", {"proposal_id": str(existing)})
            return {
                "cache_hit": True,
                "result": {**state["result"], "proposal_id": str(existing), "reused": True},
            }
        trace.step("decide_llm", "decision", "call_model", {})
        return {}

    def after_decide(state: RegressionState) -> str:
        return "end" if state.get("degraded_reason") or state.get("cache_hit") else "llm_draft"

    def llm_draft(state: RegressionState) -> RegressionState:
        request, block = agent.build_request(state["items"], state["frameworks"])
        call = call_model(deps, "llm_draft", request, block)
        if call.result is None:
            return {"degraded_reason": call.reason, "used_llm": call.used}
        out = call.result.output
        assert isinstance(out, agent.RegressionDraft)
        draft, problem = agent.validate(out, set(block.included_ids), set(state["known_names"]))
        if draft is None:
            trace.step("validate", "policy", "invalid_output", {"why": problem})
            return {"degraded_reason": "invalid_output", "used_llm": True}
        trace.step(
            "validate",
            "policy",
            "ok",
            {
                "risk_flags": draft["risk_flags"],
                "overlap": draft["overlap"],
                "framework": draft["framework"],
            },
        )
        return {"used_llm": True, "draft": draft}

    def after_draft(state: RegressionState) -> str:
        return "end" if state.get("degraded_reason") else "store_proposal"

    def store_proposal(state: RegressionState) -> RegressionState:
        recheck_run_access(deps)
        fid = uuid.UUID(state["finding_id"]) if state.get("finding_id") else None
        rid = uuid.UUID(state["result_id"]) if state.get("result_id") else None
        aid = uuid.UUID(state["alert_id"]) if state.get("alert_id") else None
        gid = uuid.UUID(state["group_id"]) if state.get("group_id") else None
        pid = proposals.insert(
            deps.db,
            project_id=deps.project_id,
            finding_id=fid,
            result_id=rid,
            alert_id=aid,
            event_group_id=gid,
            agent_run_id=deps.run_id,
            proposed_by=deps.user.id,
            draft=state["draft"],
        )
        deps.db.commit()
        trace.step("store_proposal", "policy", "proposed", {"proposal_id": str(pid)})
        d = state["draft"]
        return {
            "result": {
                **state["result"],
                "proposal_id": str(pid),
                "risk_flags": d["risk_flags"],
                "overlap": d["overlap"],
                "output": {"proposal_id": str(pid)},
            }
        }

    g: Any = StateGraph(RegressionState)
    g.add_node("load_subject", load_subject)
    g.add_node("decide_llm", decide_llm)
    g.add_node("llm_draft", llm_draft)
    g.add_node("store_proposal", store_proposal)
    g.set_entry_point("load_subject")
    g.add_conditional_edges("load_subject", after_load, {"decide_llm": "decide_llm", "end": END})
    g.add_conditional_edges("decide_llm", after_decide, {"llm_draft": "llm_draft", "end": END})
    g.add_conditional_edges(
        "llm_draft", after_draft, {"store_proposal": "store_proposal", "end": END}
    )
    g.add_edge("store_proposal", END)
    return g.compile()
