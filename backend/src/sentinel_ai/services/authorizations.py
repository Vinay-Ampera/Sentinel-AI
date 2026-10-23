"""Target authorization for remote development/staging URLs, and the execution gate.

A remote target may be contacted only inside an *approved, unexpired* authorization that
covers the check's risk level, paths and (for active checks) methods. Localhost sources are
limited to loopback by validation and need none. Production is blocked by default: it needs
the global policy flag, a Super Admin decision by someone other than the requester, a
written justification, and a window of at most 24 hours. The gate runs when a plan is
submitted and must run again in the worker immediately before execution (Stage 7).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from sentinel_ai.core.errors import DomainError
from sentinel_ai.repositories import plans, projects
from sentinel_ai.repositories.identity import UserRecord
from sentinel_ai.repositories.plans import AuthorizationRecord
from sentinel_ai.repositories.projects import SourceRecord
from sentinel_ai.services import audit
from sentinel_ai.services import policy as policy_service
from sentinel_ai.services.audit import RequestContext
from sentinel_ai.services.check_catalog import RISK_ORDER, URL_PATH_PARAM, max_risk
from sentinel_ai.services.policy import MAX_WINDOW_DAYS, PROD_MAX_WINDOW_HOURS, EffectivePolicy

AUTHORIZABLE_RISK = ("low", "medium", "high")
READ_METHODS = ("GET", "HEAD", "OPTIONS")
ALL_METHODS = (*READ_METHODS, "POST", "PUT", "PATCH", "DELETE")
MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
MAX_PATHS = 20


# ---- the gate ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateContext:
    sources: dict[uuid.UUID, SourceRecord]
    authorizations: dict[uuid.UUID, list[AuthorizationRecord]]
    policy: EffectivePolicy


def load_gate_context(db: Session, project_id: uuid.UUID, policy: EffectivePolicy) -> GateContext:
    sources = {s.id: s for s in projects.list_sources(db, project_id)}
    auths = {
        sid: plans.valid_authorizations_for_source(db, project_id, sid)
        for sid, s in sources.items()
        if s.source_type == "remote_url"
    }
    return GateContext(sources=sources, authorizations=auths, policy=policy)


def _covers(auth: AuthorizationRecord, risk: str, definition: dict[str, Any]) -> bool:
    if risk not in auth.allowed_risk:
        return False
    raw_path = (definition.get("parameters") or {}).get("url_path", "/")
    paths = auth.scope.get("paths") or ["/"]
    if not any(str(raw_path).startswith(str(p)) for p in paths):
        return False
    if definition.get("active_on_target"):
        return bool(MUTATING & set(auth.scope.get("methods") or []))
    return True


def gate_reason(
    gate: GateContext, source_id: uuid.UUID | None, risk: str, definition: dict[str, Any]
) -> str | None:
    """Why a test aimed at ``source_id`` must not run now (None = target is permitted)."""
    if risk not in gate.policy.allowed_risk:
        return f"Blocked: {risk}-risk checks are not allowed for this project by policy."
    if source_id is None:
        return None
    source = gate.sources.get(source_id)
    if source is None or not source.is_active:
        return "Blocked: the target source is no longer active in this project."
    if source.source_type != "remote_url":
        return None  # code sources run in the sandbox; localhost is loopback-only
    if source.environment == "production" and not gate.policy.production_allowed:
        return "Blocked: production testing is disabled by policy."
    matching = [
        a for a in gate.authorizations.get(source_id, []) if a.environment == source.environment
    ]
    if not matching:
        return "Blocked: this remote target has no approved, unexpired authorization. Request one for the source, then create a new plan."
    if not any(_covers(a, risk, definition) for a in matching):
        return "Blocked: the target authorization does not cover this check's risk level, paths or methods."
    return None


# ---- request / revoke --------------------------------------------------------------------


def _host(url: str | None) -> str:
    return (urlsplit(url or "").hostname or "").lower()


def _validate_scope(
    source: SourceRecord, paths: list[str], methods: list[str], allowed_risk: list[str]
) -> tuple[dict[str, Any], list[str]]:
    if (
        not paths
        or len(paths) > MAX_PATHS
        or any(not URL_PATH_PARAM.match(p) or ".." in p for p in paths)
    ):
        raise DomainError(
            422, "validation_failed", "paths must be 1-20 plain URL paths starting with '/'"
        )
    if not methods or any(m not in ALL_METHODS for m in methods):
        raise DomainError(
            422,
            "validation_failed",
            f"methods must be a non-empty subset of {', '.join(ALL_METHODS)}",
        )
    if not allowed_risk or any(r not in AUTHORIZABLE_RISK for r in allowed_risk):
        raise DomainError(
            422, "validation_failed", "allowed_risk must be a non-empty subset of low, medium, high"
        )
    scope = {
        "hosts": [_host(source.target_url)],  # fixed by the source; the requester cannot widen it
        "paths": sorted(set(paths)),
        "methods": sorted(set(methods), key=ALL_METHODS.index),
    }
    return scope, sorted(set(allowed_risk), key=RISK_ORDER.index)


def request_authorization(
    db: Session,
    ctx: RequestContext,
    user: UserRecord,
    project_id: uuid.UUID,
    source_id: uuid.UUID,
    *,
    environment: str,
    paths: list[str],
    methods: list[str],
    allowed_risk: list[str],
    valid_from: datetime | None,
    valid_until: datetime,
    justification: str,
) -> AuthorizationRecord:
    project = projects.get_project(db, project_id, for_update=True)
    if project is None:
        raise DomainError(404, "not_found", "Project not found")
    if project.status != "active":
        raise DomainError(409, "project_archived", "Archived projects are read-only")
    source = projects.get_source(db, project_id, source_id)  # scoped: other projects -> 404
    if source is None:
        raise DomainError(404, "not_found", "Source not found")
    if not source.is_active:
        raise DomainError(409, "source_inactive", "This source has been deactivated")
    if source.source_type != "remote_url":
        raise DomainError(
            422,
            "authorization_not_applicable",
            "Only remote URL sources need a target authorization",
        )
    if environment != source.environment:
        raise DomainError(
            422, "validation_failed", "environment must match the source's environment"
        )

    policy = policy_service.load_effective(db, project_id)
    if environment == "production" and not policy.production_allowed:
        audit.record(
            db, ctx, action="authorization.denied", outcome="denied", actor_user_id=user.id,
            project_id=project_id, target_type="source", target_id=str(source_id),
            detail={"reason": "production_blocked_by_policy"},
        )  # fmt: skip
        db.commit()  # persist the denial; the request transaction is about to roll back
        raise DomainError(403, "policy_blocked", "Production testing is blocked by policy")

    scope, risks = _validate_scope(source, paths, methods, allowed_risk)
    now = datetime.now(UTC)
    start = valid_from or now
    if start.tzinfo is None or valid_until.tzinfo is None:
        raise DomainError(422, "validation_failed", "Timestamps must include a timezone offset")
    longest = (
        timedelta(hours=PROD_MAX_WINDOW_HOURS)
        if environment == "production"
        else timedelta(days=MAX_WINDOW_DAYS)
    )
    if valid_until <= max(start, now):
        raise DomainError(
            422, "validation_failed", "valid_until must be in the future and after valid_from"
        )
    if valid_until - start > longest:
        raise DomainError(
            422, "validation_failed", f"The authorization window may be at most {longest} long"
        )
    if plans.pending_authorization(db, project_id, source_id, environment):
        raise DomainError(
            409, "conflict", "A pending authorization request already exists for this source"
        )

    auth = plans.insert_authorization(
        db, project_id=project_id, source_id=source_id, environment=environment, scope=scope,
        allowed_risk=risks, requested_by=user.id, justification=justification,
        valid_from=start, valid_until=valid_until,
    )  # fmt: skip
    approval_id = plans.insert_authorization_approval(db, auth.id, max_risk(*risks), user.id)
    audit.record(
        db, ctx, action="authorization.request", outcome="success", actor_user_id=user.id,
        project_id=project_id, target_type="authorization", target_id=str(auth.id),
        detail={"source_id": str(source_id), "environment": environment, "allowed_risk": risks,
                "approval_id": str(approval_id), "valid_until": valid_until.isoformat()},
    )  # fmt: skip
    return auth


def list_authorizations(db: Session, project_id: uuid.UUID) -> list[AuthorizationRecord]:
    return plans.list_authorizations(db, project_id)


def revoke_authorization(
    db: Session,
    ctx: RequestContext,
    user: UserRecord,
    project_id: uuid.UUID,
    authorization_id: uuid.UUID,
) -> AuthorizationRecord:
    auth = plans.get_authorization(db, project_id, authorization_id, for_update=True)
    if auth is None:
        raise DomainError(404, "not_found", "Authorization not found")
    if auth.status != "approved":
        raise DomainError(409, "conflict", "Only an approved authorization can be revoked")
    revoked = plans.revoke_authorization(db, authorization_id)
    audit.record(
        db, ctx, action="authorization.revoke", outcome="success", actor_user_id=user.id,
        project_id=project_id, target_type="authorization", target_id=str(authorization_id),
        detail={"environment": auth.environment},
    )  # fmt: skip
    return revoked
