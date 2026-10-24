"""Approval policy: effective policy, risk routing, and who may decide.

Principles (docs/SECURITY_AND_SAFETY.md, ADR-0003 as amended):
  * The user who runs tests on a project is responsible for them. Approval is requested from
    people with an *explicit grant on that project*, never from someone merely because of
    their role, and never from the requester.
  * The project owner (manage access) controls, for their project and within organization
    policy, which risk levels may be planned (``allowed_risk_levels``), which need approval
    (``approval_required_risk_levels``) and who approves each level (``risk_approvers``).
  * Organization policy bounds that: it sets the allowed levels, the floor that always needs
    approval (high, critical), the roles that may ever approve high/critical, and whether
    production testing exists at all. A project can only be stricter.
  * Missing or malformed stored values fall back to the safest reading.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from sentinel_ai.core.errors import DomainError
from sentinel_ai.core.permissions import AccessLevel, Permission, Role, has_permission
from sentinel_ai.repositories import identity, policies, project_access
from sentinel_ai.services import audit, observability_policy
from sentinel_ai.services.audit import RequestContext
from sentinel_ai.services.check_catalog import RISK_ORDER

APPROVAL_FLOOR = frozenset({"high", "critical"})
ALL_LEVELS = frozenset(RISK_ORDER)
# Roles an organization may allow to approve high/critical risk. Developers are NOT in the
# default: they are admitted only by an explicit organization-level setting (Super Admin).
DEFAULT_HIGH_RISK_ROLES = frozenset({Role.ADMIN.value, Role.SUPER_ADMIN.value})
HIGH_RISK_ROLE_CHOICES = DEFAULT_HIGH_RISK_ROLES | {Role.DEVELOPER.value}
GLOBAL_KEYS = (
    "production_testing",
    "approval_required_risk_levels",
    "allowed_risk_levels",
    "high_risk_approver_roles",
    "alert_threshold_bounds",
)
PROJECT_KEYS = (
    "production_testing",
    "approval_required_risk_levels",
    "allowed_risk_levels",
    "risk_approvers",
    "observability_ingest",
    "alert_thresholds",
)
MAX_APPROVERS_PER_LEVEL = 10
PROD_MAX_WINDOW_HOURS = 24
MAX_WINDOW_DAYS = 30


@dataclass(frozen=True)
class EffectivePolicy:
    production_allowed: bool
    approval_required: frozenset[str]  # levels that need a human decision
    allowed_risk: frozenset[str]  # levels that may be planned at all
    high_risk_roles: frozenset[str]  # roles that may ever approve high/critical
    approvers: dict[str, frozenset[str]]  # level -> designated user ids (project-chosen)

    def snapshot(self) -> dict[str, Any]:
        def order(levels: frozenset[str]) -> list[str]:
            return sorted(levels, key=RISK_ORDER.index)

        return {
            "production_testing": {"allowed": self.production_allowed},
            "approval_required_risk_levels": order(self.approval_required),
            "allowed_risk_levels": order(self.allowed_risk),
            "high_risk_approver_roles": sorted(self.high_risk_roles),
            "risk_approvers": {k: sorted(v) for k, v in sorted(self.approvers.items())},
        }


def _levels(value: Any, allowed: frozenset[str] = ALL_LEVELS) -> frozenset[str] | None:
    """A list of words within ``allowed``, else None (malformed)."""
    if isinstance(value, list) and all(isinstance(v, str) and v in allowed for v in value):
        return frozenset(value)
    return None


def _allowed_flag(value: Any) -> bool | None:
    if isinstance(value, dict) and isinstance(value.get("allowed"), bool):
        return bool(value["allowed"])
    return None


def _restriction(rows: dict[str, Any], key: str) -> frozenset[str]:
    """A restricting list: absent = no restriction, malformed = most restrictive (low only)."""
    if key not in rows:
        return ALL_LEVELS
    return _levels(rows[key]) or frozenset({"low"})


def _approvers(value: Any) -> dict[str, frozenset[str]]:
    out: dict[str, frozenset[str]] = {}
    if not isinstance(value, dict):
        return out
    for level, ids in value.items():
        if level in ALL_LEVELS and isinstance(ids, list) and all(isinstance(i, str) for i in ids):
            out[level] = frozenset(ids)
    return out


def merge(global_rows: dict[str, Any], project_rows: dict[str, Any]) -> EffectivePolicy:
    g_allowed = _allowed_flag(global_rows.get("production_testing")) is True
    p_allowed = _allowed_flag(project_rows.get("production_testing"))
    required = (
        APPROVAL_FLOOR
        | (_levels(global_rows.get("approval_required_risk_levels")) or frozenset())
        | (_levels(project_rows.get("approval_required_risk_levels")) or frozenset())
    )
    if "high_risk_approver_roles" in global_rows:  # malformed or empty -> strictest reading
        roles = _levels(global_rows["high_risk_approver_roles"], HIGH_RISK_ROLE_CHOICES)
        high_risk_roles = roles or frozenset({Role.SUPER_ADMIN.value})
    else:
        high_risk_roles = DEFAULT_HIGH_RISK_ROLES
    return EffectivePolicy(
        production_allowed=g_allowed and p_allowed is not False,
        approval_required=required,
        allowed_risk=_restriction(global_rows, "allowed_risk_levels")
        & _restriction(project_rows, "allowed_risk_levels"),
        high_risk_roles=high_risk_roles,
        approvers=_approvers(project_rows.get("risk_approvers")),
    )


def load_effective(db: Session, project_id: uuid.UUID) -> EffectivePolicy:
    return merge(policies.global_rows(db), policies.project_rows(db, project_id))


def requires_approval(risk: str, always: bool, policy: EffectivePolicy) -> bool:
    return always or risk in policy.approval_required or risk in APPROVAL_FLOOR


# ---- who may decide ----------------------------------------------------------------


@dataclass(frozen=True)
class Denial:
    code: str
    message: str


def eligibility_denial(
    *,
    role: str,
    user_id: uuid.UUID,
    risk: str,
    is_requester: bool,
    level: AccessLevel,
    policy: EffectivePolicy,
) -> Denial | None:
    """Why this user may not approve work of ``risk`` on this project (None = eligible).

    Needs an explicit project grant (``level`` comes from it), never the requester, and the
    organization's role bound for high/critical. Within that, the project's own designation
    decides; without one, project managers (the owner and anyone they gave manage access)."""
    if is_requester:
        return Denial("forbidden", "You cannot approve work you requested")
    if risk in APPROVAL_FLOOR and role not in policy.high_risk_roles:
        return Denial(
            "forbidden", "Organization policy does not allow your role to approve high-risk work"
        )
    designated = policy.approvers.get(risk)
    if designated:
        if str(user_id) not in designated:
            return Denial("forbidden", f"You are not a designated approver for {risk}-risk work")
        return None
    if level < AccessLevel.MANAGE:
        return Denial(
            "forbidden",
            f"{risk.capitalize()}-risk approval is for project managers or designated approvers",
        )
    return None


def authorization_decision_denial(
    *,
    role: str,
    user_id: uuid.UUID,
    environment: str,
    risk: str,
    is_requester: bool,
    level: AccessLevel,
    policy: EffectivePolicy,
) -> Denial | None:
    if is_requester:
        return Denial("forbidden", "You cannot decide an authorization you requested")
    if environment == "production":
        if not policy.production_allowed:
            return Denial("policy_blocked", "Production testing is blocked by policy")
        if not has_permission(role, Permission.APPROVE_PRODUCTION):
            return Denial("forbidden", "Only a Super Admin can authorize production testing")
        return None
    if not has_permission(role, Permission.APPROVE_REMOTE_TARGET):
        return Denial(
            "forbidden", "Organization policy reserves remote-target authorization to Admins"
        )  # noqa: E501
    return eligibility_denial(
        role=role, user_id=user_id, risk=risk, is_requester=is_requester, level=level, policy=policy
    )


# ---- policy administration ---------------------------------------------------------


def _uuid_lists(value: Any) -> dict[str, list[str]]:
    bad = DomainError(
        422,
        "validation_failed",
        'Value must map risk levels to at most 10 user ids, e.g. {"high": ["<user id>"]}',
    )
    if not isinstance(value, dict):
        raise bad
    out: dict[str, list[str]] = {}
    for level, ids in value.items():
        if (
            level not in ALL_LEVELS
            or not isinstance(ids, list)
            or len(ids) > MAX_APPROVERS_PER_LEVEL
        ):
            raise bad
        try:
            out[level] = sorted({str(uuid.UUID(i)) for i in ids if isinstance(i, str)})
        except ValueError:
            raise bad from None
        if len(out[level]) != len(ids):
            raise bad
    return out


def validate_value(
    key: str, value: Any, *, project_scope: bool, global_rows: dict[str, Any] | None = None
) -> Any:
    if key not in (PROJECT_KEYS if project_scope else GLOBAL_KEYS):
        raise DomainError(422, "validation_failed", f"Policy key '{key}' is not editable here")
    if key == "production_testing":
        flag = _allowed_flag(value)
        if flag is None or set(value) != {"allowed"}:
            raise DomainError(422, "validation_failed", 'Value must be {"allowed": true|false}')
        return {"allowed": flag}
    if key == "risk_approvers":
        return _uuid_lists(value)
    if key == "observability_ingest":
        return observability_policy.validate_ingest(value)
    if key == "alert_thresholds":
        return observability_policy.validate_thresholds(
            value, observability_policy.effective_bounds(global_rows)
        )
    if key == "alert_threshold_bounds":
        return observability_policy.validate_bounds(value)
    allowed = HIGH_RISK_ROLE_CHOICES if key == "high_risk_approver_roles" else ALL_LEVELS
    items = _levels(value, allowed)
    if items is None or (key in ("allowed_risk_levels", "high_risk_approver_roles") and not items):
        raise DomainError(
            422, "validation_failed", f"Value must be a list of: {', '.join(sorted(allowed))}"
        )
    return sorted(items, key=lambda v: RISK_ORDER.index(v) if v in RISK_ORDER else 0)


def _check_approvers(
    db: Session, project_id: uuid.UUID, approvers: dict[str, list[str]], policy: EffectivePolicy
) -> None:
    """Designees must be active users who already hold a grant on this project (a designation
    never grants access), and, for high/critical, hold a role organization policy allows."""
    for level, ids in approvers.items():
        for raw in ids:
            user = identity.get_user(db, uuid.UUID(raw))
            ok = (
                user is not None
                and user.is_active
                and bool(project_access.access_grants(db, project_id, user.id))
                and (level not in APPROVAL_FLOOR or user.role_name in policy.high_risk_roles)
            )
            if not ok:
                raise DomainError(
                    422,
                    "invalid_approver",
                    "Each approver must be an active member of this project"
                    + (
                        " with a role organization policy allows for high-risk approval"
                        if level in APPROVAL_FLOOR
                        else ""
                    ),
                )


def set_policy(
    db: Session,
    ctx: RequestContext,
    *,
    actor_id: uuid.UUID,
    role: str,
    key: str,
    value: Any,
    project_id: uuid.UUID | None,
) -> dict[str, Any]:
    """Callers have already checked: global -> POLICY_GLOBAL; project -> manage access."""
    clean = validate_value(
        key, value, project_scope=project_id is not None,
        global_rows=policies.global_rows(db) if project_id is not None else None,
    )  # fmt: skip
    if project_id is None and not has_permission(role, Permission.POLICY_GLOBAL):
        raise DomainError(403, "forbidden", "You do not have permission to change this policy")
    if project_id is not None:
        # A project can only restrict: it may never switch production testing on.
        if key == "production_testing" and clean["allowed"]:
            audit.record(
                db,
                ctx,
                action="policy.denied",
                outcome="denied",
                actor_user_id=actor_id,
                project_id=project_id,
                detail={"key": key, "reason": "project cannot enable production"},
            )
            db.commit()
            raise DomainError(
                403, "policy_blocked", "A project policy cannot enable production testing"
            )
        if key == "risk_approvers":
            _check_approvers(db, project_id, clean, load_effective(db, project_id))
        policies.upsert_project(db, project_id, key, clean, actor_id)
    else:
        policies.upsert_global(db, key, clean, actor_id)
    audit.record(
        db,
        ctx,
        action="policy.update",
        outcome="success",
        actor_user_id=actor_id,
        project_id=project_id,
        target_type="policy",
        target_id=key,
        detail={"scope": "project" if project_id else "global", "key": key, "value": clean},
    )
    return {"key": key, "value": clean}


def global_rows(db: Session) -> dict[str, Any]:
    return policies.global_rows(db)


def project_rows(db: Session, project_id: uuid.UUID) -> dict[str, Any]:
    return policies.project_rows(db, project_id)
