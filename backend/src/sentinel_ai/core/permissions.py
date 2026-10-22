"""Role -> capability matrix (docs/SECURITY_AND_SAFETY.md) and project access levels.

Role grants capabilities; project access grants scope. A route needing both checks both.
"Policy-dependent" rows of the matrix (Developer approvals "only if policy delegates",
Admin "in scope") are NOT granted here: they need the policy/scope data that arrives with
the approval and project stages, so the deterministic default is deny.
"""

from enum import IntEnum, StrEnum


class Role(StrEnum):
    DEVELOPER = "developer"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"


class Permission(StrEnum):
    # identity
    SESSION_MANAGE_OWN = "session.manage_own"
    # projects and runs (scope additionally requires project access)
    PROJECT_CREATE = "project.create"
    PROJECT_VIEW = "project.view"
    SOURCE_MANAGE = "project.source_manage"
    PROJECT_ANALYZE = "project.analyze"
    PLAN_AND_RUN = "run.plan_and_run"
    EVIDENCE_AND_TRIAGE = "finding.triage"
    FINDING_RISK_DECISION = "finding.risk_decision"
    MEMBERS_MANAGE = "project.members_manage"
    # approvals
    APPROVE_LOW_MEDIUM_RISK = "approval.low_medium"
    APPROVE_HIGH_RISK = "approval.high_risk"
    APPROVE_REMOTE_TARGET = "approval.remote_target"
    APPROVE_PRODUCTION = "approval.production"
    # administration
    USER_LIST = "user.list"
    USER_MANAGE_DEVELOPERS = "user.manage_developers"
    USER_MANAGE_PRIVILEGED = "user.manage_privileged"
    POLICY_PROJECT_SCOPE = "policy.project_scope"
    POLICY_GLOBAL = "policy.global"
    AUDIT_READ_OWN = "audit.read_own"
    AUDIT_READ_SCOPE = "audit.read_scope"
    AUDIT_READ_ALL = "audit.read_all"


_DEVELOPER = frozenset(
    {
        Permission.SESSION_MANAGE_OWN,
        Permission.PROJECT_CREATE,
        Permission.PROJECT_VIEW,
        Permission.SOURCE_MANAGE,
        Permission.PROJECT_ANALYZE,
        Permission.PLAN_AND_RUN,
        Permission.EVIDENCE_AND_TRIAGE,
        Permission.MEMBERS_MANAGE,
        Permission.AUDIT_READ_OWN,
    }
)
_ADMIN = _DEVELOPER | {
    Permission.FINDING_RISK_DECISION,
    Permission.APPROVE_LOW_MEDIUM_RISK,
    Permission.APPROVE_HIGH_RISK,
    Permission.APPROVE_REMOTE_TARGET,
    Permission.USER_LIST,
    Permission.USER_MANAGE_DEVELOPERS,
    Permission.POLICY_PROJECT_SCOPE,
    Permission.AUDIT_READ_SCOPE,
}
_SUPER_ADMIN = _ADMIN | {
    Permission.APPROVE_PRODUCTION,
    Permission.USER_MANAGE_PRIVILEGED,
    Permission.POLICY_GLOBAL,
    Permission.AUDIT_READ_ALL,
}

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.DEVELOPER: _DEVELOPER,
    Role.ADMIN: frozenset(_ADMIN),
    Role.SUPER_ADMIN: frozenset(_SUPER_ADMIN),
}


def role_from_name(name: str) -> Role | None:
    try:
        return Role(name)
    except ValueError:
        return None


def has_permission(role_name: str, permission: Permission) -> bool:
    """Unknown roles have no permissions."""
    role = role_from_name(role_name)
    return role is not None and permission in ROLE_PERMISSIONS[role]


class AccessLevel(IntEnum):
    """Per-project access; higher implies lower (read < run < manage)."""

    READ = 1
    RUN = 2
    MANAGE = 3


def access_level_from_name(name: str | None) -> AccessLevel | None:
    return {"read": AccessLevel.READ, "run": AccessLevel.RUN, "manage": AccessLevel.MANAGE}.get(
        name or ""
    )
