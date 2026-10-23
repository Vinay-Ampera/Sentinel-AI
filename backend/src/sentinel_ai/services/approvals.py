"""Approval decisions for plans and target authorizations, and the approval inbox.

Authority is decided here by deterministic policy code (``services/policy.py``) using the
caller's role, project access, the approval's risk level and the *current* effective policy.
A refused decision is audited as ``approval.denied`` before the error is raised. A plan can
only be approved while its content still hashes to the value recorded at submission, so what
was reviewed is exactly what becomes runnable.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from sentinel_ai.core.errors import DomainError
from sentinel_ai.core.permissions import AccessLevel
from sentinel_ai.repositories import plans, projects
from sentinel_ai.repositories.identity import UserRecord
from sentinel_ai.repositories.plans import ApprovalRecord
from sentinel_ai.services import audit
from sentinel_ai.services import policy as policy_service
from sentinel_ai.services import project_access as project_access_service
from sentinel_ai.services.audit import RequestContext
from sentinel_ai.services.plans import RUNNABLE, content_hash
from sentinel_ai.services.policy import APPROVAL_FLOOR, Denial

STATUS_FILTERS = ("pending", "approved", "rejected")
MIN_REASON = 5
MIN_STRONG_REASON = 10


def _deny(
    db: Session,
    ctx: RequestContext,
    user: UserRecord,
    approval: ApprovalRecord,
    denial: Denial,
) -> DomainError:
    """Persist the refusal (the request transaction rolls back) and build the error."""
    audit.record(
        db, ctx, action="approval.denied", outcome="denied", actor_user_id=user.id,
        project_id=approval.project_id, target_type="approval", target_id=str(approval.id),
        detail={"risk": approval.risk_level, "reason": denial.message},
    )  # fmt: skip
    db.commit()
    return DomainError(403, denial.code, denial.message)


def decide(
    db: Session,
    ctx: RequestContext,
    user: UserRecord,
    approval_id: uuid.UUID,
    *,
    decision: str,
    reason: str | None,
) -> ApprovalRecord:
    if decision not in ("approved", "rejected"):
        raise DomainError(422, "validation_failed", "decision must be 'approved' or 'rejected'")
    reason = (reason or "").strip() or None
    if decision == "rejected" and (reason is None or len(reason) < MIN_REASON):
        raise DomainError(
            422,
            "validation_failed",
            f"A rejection needs a reason of at least {MIN_REASON} characters",
        )

    approval = plans.get_approval(db, approval_id, for_update=True)
    if approval is None:
        raise DomainError(404, "not_found", "Approval not found")
    project_access_service.authorize_project(db, ctx, user, approval.project_id, AccessLevel.READ)
    # Decisions need an explicit grant. Temporary break-glass access is read-only and never
    # counts, so a Super Admin must already be a project member to approve (production too).
    level = project_access_service.resolve_explicit_access(db, user, approval.project_id)
    if level is None:
        raise _deny(
            db,
            ctx,
            user,
            approval,
            Denial("forbidden", "Break-glass access is read-only and cannot decide approvals"),
        )
    if approval.decision != "pending":
        raise DomainError(409, "already_decided", "This approval has already been decided")

    policy = policy_service.load_effective(db, approval.project_id)
    if approval.plan_id is not None:
        _decide_plan(db, ctx, user, approval, level, policy, decision, reason)
    else:
        _decide_authorization(db, ctx, user, approval, level, policy, decision, reason)

    plans.decide_approval(db, approval_id, decision=decision, decided_by=user.id, reason=reason)
    audit.record(
        db, ctx, action="approval.decision", outcome="success", actor_user_id=user.id,
        project_id=approval.project_id, target_type="approval", target_id=str(approval_id),
        detail={"decision": decision, "risk": approval.risk_level,
                "plan_id": str(approval.plan_id) if approval.plan_id else None,
                "authorization_id": str(approval.authorization_id) if approval.authorization_id else None,  # fmt: skip
                "requested_by": str(approval.requested_by), "reason": reason},
    )  # fmt: skip
    decided = plans.get_approval(db, approval_id)
    assert decided is not None
    return decided


def _decide_plan(
    db: Session,
    ctx: RequestContext,
    user: UserRecord,
    approval: ApprovalRecord,
    level: AccessLevel,
    policy: policy_service.EffectivePolicy,
    decision: str,
    reason: str | None,
) -> None:
    assert approval.plan_id is not None
    plan = plans.get_plan(db, approval.plan_id, for_update=True)
    if plan is None or plan.project_id != approval.project_id:
        raise DomainError(404, "not_found", "Plan not found")
    if plan.status != "pending_approval":
        raise DomainError(409, "conflict", "The plan is no longer waiting for approval")
    tests = plans.list_tests(db, plan.id)
    if plan.content_sha256 is None or content_hash(plan, tests) != plan.content_sha256:
        raise DomainError(409, "plan_changed", "The plan no longer matches what was submitted")

    is_requester = approval.requested_by == user.id
    if decision == "rejected" and is_requester:
        # The submitter may withdraw their own request; they never approve it.
        if level < AccessLevel.RUN:
            raise _deny(
                db, ctx, user, approval, Denial("forbidden", "Withdrawing needs run access")
            )
    else:
        denial = policy_service.eligibility_denial(
            role=user.role_name,
            user_id=user.id,
            risk=approval.risk_level,
            is_requester=is_requester,
            level=level,
            policy=policy,
        )
        if denial is not None:
            raise _deny(db, ctx, user, approval, denial)
    if (
        decision == "approved"
        and approval.risk_level in APPROVAL_FLOOR
        and (reason is None or len(reason) < MIN_STRONG_REASON)
    ):
        raise DomainError(
            422,
            "validation_failed",
            f"Approving a {approval.risk_level}-risk plan needs a written reason of at least {MIN_STRONG_REASON} characters",
        )

    if decision == "approved":
        plans.set_plan_status(db, plan.id, "approved")
        plans.set_tests_status(db, plan.id, RUNNABLE, "approved")
    else:
        plans.set_plan_status(db, plan.id, "rejected")


def _decide_authorization(
    db: Session,
    ctx: RequestContext,
    user: UserRecord,
    approval: ApprovalRecord,
    level: AccessLevel,
    policy: policy_service.EffectivePolicy,
    decision: str,
    reason: str | None,
) -> None:
    assert approval.authorization_id is not None
    auth = plans.get_authorization(
        db, approval.project_id, approval.authorization_id, for_update=True
    )
    if auth is None:
        raise DomainError(404, "not_found", "Authorization not found")
    if auth.status != "pending":
        raise DomainError(409, "conflict", "The authorization is no longer pending")
    # Rejecting is always safe; only an approval needs the production gate.
    env = auth.environment if decision == "approved" else "staging"
    denial = policy_service.authorization_decision_denial(
        role=user.role_name,
        user_id=user.id,
        environment=env,
        risk=approval.risk_level,
        is_requester=auth.requested_by == user.id,
        level=level,
        policy=policy,
    )
    if denial is not None:
        raise _deny(db, ctx, user, approval, denial)
    if decision == "approved":
        if auth.valid_until is None or auth.valid_until <= datetime.now(UTC):
            raise DomainError(
                409, "authorization_expired", "The requested window has already ended"
            )
        if auth.environment == "production" and (reason is None or len(reason) < MIN_STRONG_REASON):
            raise DomainError(
                422,
                "validation_failed",
                f"Production needs a written reason of at least {MIN_STRONG_REASON} characters",
            )
    plans.decide_authorization(db, auth.id, status=decision, decided_by=user.id, note=reason)


def list_approvals(
    db: Session,
    ctx: RequestContext,
    user: UserRecord,
    status: str,
    limit: int,
) -> list[ApprovalRecord]:
    """Approvals in projects the caller can reach. For ``pending`` only items the caller
    could actually approve now are returned; decided items are shown to anyone with read access."""
    if status != "all" and status not in STATUS_FILTERS:
        raise DomainError(
            422, "validation_failed", "status must be pending, approved, rejected or all"
        )
    ids = [
        p.id
        for p, _ in projects.list_projects(
            db, user.id, all_projects=False, include_archived=True, limit=1000
        )
    ]
    if not ids:
        return []
    rows = plans.list_approvals(db, None if status == "all" else status, ids, limit * 4)
    out: list[ApprovalRecord] = []
    levels: dict[uuid.UUID, AccessLevel | None] = {}
    policies: dict[uuid.UUID, policy_service.EffectivePolicy] = {}
    for a in rows:
        if a.decision == "pending":
            if a.project_id not in levels:
                levels[a.project_id] = project_access_service.resolve_explicit_access(
                    db, user, a.project_id
                )
                policies[a.project_id] = policy_service.load_effective(db, a.project_id)
            level = levels[a.project_id]
            if level is None:
                continue
            if a.plan_id is not None:
                denial = policy_service.eligibility_denial(
                    role=user.role_name,
                    user_id=user.id,
                    risk=a.risk_level,
                    is_requester=a.requested_by == user.id,
                    level=level,
                    policy=policies[a.project_id],
                )
            else:
                assert a.authorization_id is not None
                target = plans.get_authorization(db, a.project_id, a.authorization_id)
                denial = policy_service.authorization_decision_denial(
                    role=user.role_name,
                    user_id=user.id,
                    environment=target.environment if target else "production",
                    risk=a.risk_level,
                    is_requester=a.requested_by == user.id,
                    level=level,
                    policy=policies[a.project_id],
                )
            if denial is not None:
                continue
        out.append(a)
        if len(out) >= limit:
            break
    return out


def viewer_can_approve(db: Session, user: UserRecord, approval: ApprovalRecord | None) -> bool:
    """UI hint only (the decision endpoint re-checks): could this user approve right now?"""
    if approval is None or approval.decision != "pending" or approval.plan_id is None:
        return False
    level = project_access_service.resolve_explicit_access(db, user, approval.project_id)
    if level is None:
        return False
    return (
        policy_service.eligibility_denial(
            role=user.role_name,
            user_id=user.id,
            risk=approval.risk_level,
            is_requester=approval.requested_by == user.id,
            level=level,
            policy=policy_service.load_effective(db, approval.project_id),
        )
        is None
    )
