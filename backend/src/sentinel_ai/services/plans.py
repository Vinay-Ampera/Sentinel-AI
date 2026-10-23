"""Test plans: generation, editing, submission and policy routing (Stage 6).

A plan is built only from the check catalog (deterministic); prompts and developers select
catalog entries, they never supply commands or risk levels. ``submit_plan`` is the single
place where a draft is frozen: it re-checks target authorization, recomputes which tests need
approval under the current policy, binds the result to a SHA-256 of the reviewed content, and
either approves automatically (nothing needs a human) or opens an approval. Nothing here
executes anything; approving a plan only makes it eligible for a later run.
"""

import hashlib
import json
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from sentinel_ai.core.errors import DomainError
from sentinel_ai.core.permissions import AccessLevel
from sentinel_ai.repositories import plans, projects
from sentinel_ai.repositories.identity import UserRecord
from sentinel_ai.repositories.plans import ApprovalRecord, PlannedTestRecord, PlanRecord
from sentinel_ai.services import audit, authorizations
from sentinel_ai.services import policy as policy_service
from sentinel_ai.services import project_access as project_access_service
from sentinel_ai.services.audit import RequestContext
from sentinel_ai.services.check_catalog import (
    CATALOG,
    MAX_TESTS_PER_PLAN,
    InvalidTestDefinition,
    PlanContext,
    Proposal,
    SourceInfo,
    from_developer,
    from_prompt,
    max_risk,
    recommend,
)
from sentinel_ai.services.policy import EffectivePolicy

PLAN_MODES = ("automatic", "prompt_based", "developer_defined")
RUNNABLE = "planned"


@dataclass(frozen=True)
class DevTestInput:
    check_id: str
    source_id: uuid.UUID | None = None
    name: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    script_artifact_id: uuid.UUID | None = None


@dataclass(frozen=True)
class PlanDetail:
    plan: PlanRecord
    tests: list[PlannedTestRecord]
    approval: ApprovalRecord | None


# ---- helpers ------------------------------------------------------------------------------


def content_hash(plan: PlanRecord, tests: list[PlannedTestRecord]) -> str:
    """SHA-256 over everything a reviewer approves. Execution status is excluded on purpose:
    it changes as checks run, the reviewed content does not."""
    payload = {
        "project_id": str(plan.project_id),
        "snapshot_id": str(plan.snapshot_id) if plan.snapshot_id else None,
        "version": plan.version,
        "mode": plan.plan_mode,
        "prompt": plan.prompt,
        "tests": [
            {
                "ordinal": t.ordinal,
                "name": t.name,
                "category": t.category,
                "tool": t.tool,
                "origin": t.origin,
                "definition": t.definition,
                "script_artifact_id": str(t.script_artifact_id) if t.script_artifact_id else None,
                "risk_level": t.risk_level,
                "requires_approval": t.requires_approval,
                "rationale": t.rationale,
            }
            for t in tests
        ],
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def _plan_risk(tests: list[PlannedTestRecord] | list[Proposal]) -> str:
    risks = [t.risk_level for t in tests if t.status == RUNNABLE]
    return max_risk(*risks) if risks else "low"


def _lock_active_project(db: Session, project_id: uuid.UUID) -> projects.ProjectRecord:
    project = projects.get_project(db, project_id, for_update=True)
    if project is None:
        raise DomainError(404, "not_found", "Project not found")
    if project.status != "active":
        raise DomainError(409, "project_archived", "Archived projects are read-only")
    return project


def _build_context(
    db: Session, project: projects.ProjectRecord, snapshot_id: uuid.UUID | None
) -> tuple[PlanContext, list[str]]:
    sources = [s for s in projects.list_sources(db, project.id) if s.is_active]
    infos = tuple(SourceInfo(s.id, s.source_type, s.name, s.environment) for s in sources)
    notes: list[str] = []
    snapshot = None
    if snapshot_id is not None:
        snapshot = projects.get_snapshot(db, snapshot_id)
        if snapshot is None or snapshot.project_id != project.id:  # other project: same 404
            raise DomainError(404, "not_found", "Analysis snapshot not found")
        if snapshot.status != "completed":
            raise DomainError(422, "snapshot_not_completed", "That analysis did not complete")
    else:
        snapshot = next(
            (s for s in projects.list_snapshots(db, project.id, 20) if s.status == "completed"),
            None,
        )
    detected = snapshot.detected if snapshot else None
    if snapshot is not None and snapshot.source_id not in {s.id for s in sources}:
        notes.append("The analysed source is no longer active; analysis evidence was not used.")
        snapshot, detected = None, None
    if snapshot is None:
        notes.append("No completed analysis was available; evidence-dependent checks are deferred.")
    ctx = PlanContext(
        application_type=project.application_type,
        snapshot_id=snapshot.id if snapshot else None,
        detected=detected,
        snapshot_source_id=snapshot.source_id if snapshot else None,
        sources=infos,
    )
    return ctx, notes


def _store(
    db: Session,
    plan_id: uuid.UUID,
    start: int,
    proposals: list[Proposal],
    policy: EffectivePolicy,
    gate: authorizations.GateContext,
) -> None:
    for offset, p in enumerate(proposals):
        status, rationale = p.status, p.rationale
        if status == RUNNABLE:
            reason = authorizations.gate_reason(gate, p.source_id, p.risk_level, p.definition)
            if reason is not None:
                status, rationale = "blocked", f"{rationale} {reason}"
        plans.insert_test(
            db,
            plan_id=plan_id,
            ordinal=start + offset,
            name=p.name,
            category=p.category,
            tool=p.tool,
            origin=p.origin,
            definition=p.definition,
            script_artifact_id=p.script_artifact_id,
            risk_level=p.risk_level,
            requires_approval=policy_service.requires_approval(
                p.risk_level, p.always_requires_approval, policy
            ),
            rationale=rationale,
            status=status,
        )


def _developer_proposals(
    db: Session, ctx: PlanContext, project_id: uuid.UUID, items: list[DevTestInput]
) -> list[Proposal]:
    out = []
    for item in items:
        if item.script_artifact_id is not None and not plans.script_artifact_usable(
            db, project_id, item.script_artifact_id
        ):  # another project's or unvalidated artifact: indistinguishable
            raise DomainError(
                422, "invalid_test", "script_artifact_id is not an accepted script of this project"
            )
        try:
            out.append(
                from_developer(
                    ctx,
                    check_id=item.check_id,
                    source_id=item.source_id,
                    name=item.name,
                    parameters=item.parameters,
                    script_artifact_id=item.script_artifact_id,
                )
            )
        except InvalidTestDefinition as exc:
            raise DomainError(422, "invalid_test", str(exc)) from exc
    return out


def _detail(db: Session, plan: PlanRecord) -> PlanDetail:
    return PlanDetail(
        plan, plans.list_tests(db, plan.id), plans.latest_approval_for_plan(db, plan.id)
    )


# ---- create / read / edit -------------------------------------------------------------------


def create_plan(
    db: Session,
    ctx: RequestContext,
    user: UserRecord,
    project_id: uuid.UUID,
    *,
    mode: str,
    snapshot_id: uuid.UUID | None,
    prompt: str | None,
    tests: list[DevTestInput],
) -> PlanDetail:
    if mode not in PLAN_MODES:
        raise DomainError(422, "validation_failed", "Unknown plan mode")
    if (mode == "prompt_based") != (prompt is not None):
        raise DomainError(
            422,
            "validation_failed",
            "prompt is required for, and only allowed in, prompt_based mode",
        )
    if (mode == "developer_defined") != bool(tests):
        raise DomainError(
            422,
            "validation_failed",
            "tests are required for, and only allowed in, developer_defined mode",
        )
    if prompt is not None and not prompt.strip():
        raise DomainError(422, "validation_failed", "prompt must not be blank")

    project = _lock_active_project(db, project_id)
    plan_ctx, notes = _build_context(db, project, snapshot_id)
    if mode == "automatic":
        proposals = recommend(plan_ctx)
    elif mode == "prompt_based":
        assert prompt is not None
        proposals = from_prompt(plan_ctx, prompt)
        if not proposals:
            raise DomainError(
                422,
                "no_checks_matched",
                "No catalog check matched the prompt; name a kind of check such as unit tests, accessibility, API, dependency audit or security scan.",
            )
    else:
        proposals = _developer_proposals(db, plan_ctx, project_id, tests)

    policy = policy_service.load_effective(db, project_id)
    gate = authorizations.load_gate_context(db, project_id, policy)
    summary = " ".join(notes) or None
    plan = plans.insert_plan(
        db,
        project_id=project_id,
        snapshot_id=plan_ctx.snapshot_id,
        version=plans.next_version(db, project_id),
        plan_mode=mode,
        prompt=prompt,
        risk_level="low",
        summary=summary,
        created_by=user.id,
    )
    _store(db, plan.id, 1, proposals, policy, gate)
    stored = plans.list_tests(db, plan.id)
    plan = plans.update_draft(db, plan.id, summary=summary, risk_level=_plan_risk(stored))
    audit.record(
        db, ctx, action="plan.create", outcome="success", actor_user_id=user.id,
        project_id=project_id, target_type="plan", target_id=str(plan.id),
        detail={"mode": mode, "version": plan.version, "tests": len(stored),
                "by_status": dict(Counter(t.status for t in stored))},
    )  # fmt: skip
    return PlanDetail(plan, stored, None)


def list_plans(db: Session, project_id: uuid.UUID, limit: int) -> list[PlanRecord]:
    return plans.list_plans(db, project_id, limit)


def get_plan(
    db: Session, ctx: RequestContext, user: UserRecord, plan_id: uuid.UUID, minimum: AccessLevel
) -> PlanDetail:
    """Plan by id; the caller's access is resolved on the plan's own project, so an id alone
    never reaches another project's plan (unknown and inaccessible are both 404)."""
    plan = plans.get_plan(db, plan_id)
    if plan is None:
        raise DomainError(404, "not_found", "Plan not found")
    project_access_service.authorize_project(db, ctx, user, plan.project_id, minimum)
    return _detail(db, plan)


def edit_plan(
    db: Session,
    ctx: RequestContext,
    user: UserRecord,
    plan_id: uuid.UUID,
    *,
    summary: str | None,
    remove_test_ids: list[uuid.UUID],
    add_tests: list[DevTestInput],
) -> PlanDetail:
    known = plans.get_plan(db, plan_id)
    if known is None:
        raise DomainError(404, "not_found", "Plan not found")
    project_access_service.authorize_project(db, ctx, user, known.project_id, AccessLevel.RUN)
    project = _lock_active_project(db, known.project_id)
    plan = plans.get_plan(db, plan_id, for_update=True)
    assert plan is not None
    if plan.status != "draft":
        raise DomainError(409, "plan_not_editable", "Only a draft plan can be edited")

    removed = plans.delete_tests(db, plan_id, remove_test_ids) if remove_test_ids else 0
    if removed != len(set(remove_test_ids)):
        raise DomainError(
            422, "invalid_test", "remove_test_ids contains a test that is not in this plan"
        )
    existing = plans.list_tests(db, plan_id)
    if len(existing) + len(add_tests) > MAX_TESTS_PER_PLAN:
        raise DomainError(
            422, "too_many_tests", f"A plan may contain at most {MAX_TESTS_PER_PLAN} tests"
        )
    if removed:
        plans.renumber_tests(db, plan_id)
    if add_tests:
        plan_ctx, _ = _build_context(db, project, plan.snapshot_id)
        proposals = _developer_proposals(db, plan_ctx, plan.project_id, add_tests)
        policy = policy_service.load_effective(db, plan.project_id)
        gate = authorizations.load_gate_context(db, plan.project_id, policy)
        _store(db, plan_id, len(existing) + 1, proposals, policy, gate)
    stored = plans.list_tests(db, plan_id)
    plan = plans.update_draft(
        db,
        plan_id,
        summary=plan.summary if summary is None else summary,
        risk_level=_plan_risk(stored),
    )
    audit.record(
        db, ctx, action="plan.update", outcome="success", actor_user_id=user.id,
        project_id=plan.project_id, target_type="plan", target_id=str(plan_id),
        detail={"removed": removed, "added": len(add_tests), "summary_changed": summary is not None},  # fmt: skip
    )  # fmt: skip
    return PlanDetail(plan, stored, None)


# ---- submit -----------------------------------------------------------------------------------


def submit_plan(
    db: Session, ctx: RequestContext, user: UserRecord, plan_id: uuid.UUID
) -> PlanDetail:
    known = plans.get_plan(db, plan_id)
    if known is None:
        raise DomainError(404, "not_found", "Plan not found")
    project_access_service.authorize_project(db, ctx, user, known.project_id, AccessLevel.RUN)
    _lock_active_project(db, known.project_id)
    plan = plans.get_plan(db, plan_id, for_update=True)
    assert plan is not None
    if plan.status != "draft":
        raise DomainError(409, "plan_not_editable", "Only a draft plan can be submitted")

    policy = policy_service.load_effective(db, plan.project_id)
    gate = authorizations.load_gate_context(db, plan.project_id, policy)
    for t in plans.list_tests(db, plan_id):
        if t.status != RUNNABLE:
            continue
        source_id = (
            uuid.UUID(t.definition["target"]["source_id"]) if t.definition.get("target") else None
        )
        reason = authorizations.gate_reason(gate, source_id, t.risk_level, t.definition)
        needs = policy_service.requires_approval(t.risk_level, _always(t), policy)
        if reason is not None:
            plans.update_test_gate(db, t.id, status="blocked", rationale=f"{t.rationale} {reason}")
        elif needs != t.requires_approval:
            plans.update_test_gate(db, t.id, requires_approval=needs)

    tests = plans.list_tests(db, plan_id)
    runnable = [t for t in tests if t.status == RUNNABLE]
    if not runnable:
        db.commit()  # keep the gate's blocked statuses and reasons visible on the draft
        raise DomainError(
            422, "no_runnable_tests", "The plan has no test that can run; see each test's reason",
            [{"field": s, "issue": str(n)} for s, n in sorted(Counter(t.status for t in tests).items())],  # fmt: skip
        )  # fmt: skip
    risk = _plan_risk(tests)
    needs_human = any(t.requires_approval for t in runnable)
    status = "pending_approval" if needs_human else "approved"
    frozen_basis = PlanRecord(**{**plan.__dict__, "risk_level": risk})
    digest = content_hash(frozen_basis, tests)
    frozen = plans.freeze_plan(
        db, plan_id, status=status, risk_level=risk, content_sha256=digest,
        policy_snapshot=policy.snapshot(), submitted_by=user.id,
    )  # fmt: skip
    approval_id: uuid.UUID | None = None
    if needs_human:
        approval_id = plans.insert_plan_approval(db, plan_id, risk, user.id)
        action = "plan.submit"
    else:
        plans.set_tests_status(db, plan_id, RUNNABLE, "approved")
        action = "plan.auto_approved"
    audit.record(
        db, ctx, action=action, outcome="success", actor_user_id=user.id,
        project_id=plan.project_id, target_type="plan", target_id=str(plan_id),
        detail={"risk": risk, "content_sha256": digest, "policy": policy.snapshot(),
                "approval_id": str(approval_id) if approval_id else None,
                "runnable": len(runnable),
                "not_runnable": dict(Counter(t.status for t in tests if t.status != RUNNABLE))},
    )  # fmt: skip
    return _detail(db, frozen)


def _always(test: PlannedTestRecord) -> bool:
    """Checks that always need a human regardless of risk policy (intrusive, custom scripts)."""
    spec = CATALOG.get(str(test.definition.get("check_id")))
    return bool(spec and spec.always_requires_approval)
