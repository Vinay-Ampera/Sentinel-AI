"""Findings from scanners (Stage 10): ingestion, review states and verification.

Rules that hold here and nowhere else gets to bend them:
  * Scanner output is created ``unverified``; only a person can move it to ``likely`` or
    ``confirmed`` (``confirmed`` also needs evidence, enforced by the database too).
  * Every finding links to the stored scanner report that produced it.
  * A later complete scan of the same source that no longer reports a finding records a
    ``rescan`` verification attempt. It moves the finding to ``fixed``, and to
    ``verified_fixed`` only when a person had already marked it fixed. A scan that failed or
    was truncated never counts as "gone".
  * A fixed finding that a scan reports again is ``reopened``.
  * Findings from different tools that describe one issue are linked by ``services.dedup``
    (``group_id``); every finding keeps its own tool, evidence and state.
  * Reviewing needs the project ``run`` level (so break-glass, being read-only, cannot);
    ``false_positive`` and ``accepted_risk`` additionally need the risk-decision permission
    (administrators), as the permission matrix in SECURITY_AND_SAFETY.md says.
"""

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from sentinel_ai.core.errors import DomainError
from sentinel_ai.core.permissions import AccessLevel, Permission, has_permission
from sentinel_ai.execution.interface import ScanOutcome
from sentinel_ai.repositories import findings as repo
from sentinel_ai.repositories.findings import (
    AttemptRecord,
    FindingEventRecord,
    FindingEvidenceRecord,
    FindingRecord,
)
from sentinel_ai.repositories.identity import UserRecord
from sentinel_ai.services import alerts, audit, dedup
from sentinel_ai.services import project_access as project_access_service
from sentinel_ai.services.audit import RequestContext

logger = logging.getLogger(__name__)

MIN_NOTE = 10
MAX_NOTE = 1000
# What a person may set by hand. ``verified_fixed`` and ``reopened`` come only from scans.
MANUAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "new": frozenset({"triaged", "in_progress", "false_positive", "accepted_risk", "fixed"}),
    "triaged": frozenset({"in_progress", "false_positive", "accepted_risk", "fixed"}),
    "in_progress": frozenset({"triaged", "false_positive", "accepted_risk", "fixed"}),
    "reopened": frozenset({"triaged", "in_progress", "false_positive", "accepted_risk", "fixed"}),
    "fixed": frozenset({"reopened"}),
    "verified_fixed": frozenset({"reopened"}),
    "accepted_risk": frozenset({"triaged", "reopened"}),
    "false_positive": frozenset({"triaged", "reopened"}),
}
RISK_DECISIONS = frozenset({"false_positive", "accepted_risk"})  # administrators only, with a note
MANUAL_VERIFICATION = frozenset({"likely", "confirmed", "not_reproduced", "inconclusive"})
REPORT_NOTE = "Scanner report that produced or re-reported this finding."


@dataclass(frozen=True)
class IngestSummary:
    created: int = 0
    seen_again: int = 0
    reopened: int = 0
    rescan_fixed: int = 0


@dataclass(frozen=True)
class FindingDetail:
    finding: FindingRecord
    events: list[FindingEventRecord]
    evidence: list[FindingEvidenceRecord]
    attempts: list[AttemptRecord]
    related: list[FindingRecord]  # other findings in the same duplicate group


# ---- worker side ------------------------------------------------------------------------------


def _raise_reopened_alert(
    db: Session,
    project_id: uuid.UUID,
    finding: repo.FindingRecord,
    run_id: uuid.UUID,
    result_id: uuid.UUID,
) -> None:
    """Internal alert (ADR-0011), best effort in a savepoint: it must never fail the scan."""
    try:
        with db.begin_nested():
            alerts.finding_reopened(
                db, None, project_id, finding.id, title=finding.title, severity=finding.severity,
                run_id=run_id, result_id=result_id,
            )  # fmt: skip
    except Exception as exc:
        logger.warning("finding alert failed (%s)", type(exc).__name__)


def ingest_scan(
    db: Session,
    *,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    result_id: uuid.UUID,
    source_id: uuid.UUID | None,
    scan: ScanOutcome,
    report_artifact_id: uuid.UUID | None,
) -> IngestSummary:
    """Turn a scanner's valid report into findings. Idempotent per fingerprint; the caller
    commits. A finding without a stored report is still recorded, but cannot be confirmed."""
    created = seen = reopened = 0
    for f in scan.findings:
        finding_id = repo.insert_finding(
            db, project_id=project_id, run_id=run_id, result_id=result_id, source_id=source_id,
            fingerprint=f.fingerprint, title=f.title, description=f.message,
            category=f.category, detected_by=f.tool, rule_id=f.rule_id,
            file_path=f.path, line_number=f.line, severity=f.severity,
            confidence=f.confidence, limitations=scan.limitations, cwe=f.cwe,
            component=f.component, aliases=f.aliases,
        )  # fmt: skip
        if finding_id is not None:
            created += 1
            repo.insert_event(
                db, finding_id, "created", to_value="new",
                detail={"run_id": str(run_id), "tool": f.tool, "rule": f.rule_id},
            )  # fmt: skip
        else:
            existing = repo.get_by_fingerprint(db, project_id, f.fingerprint, for_update=True)
            if existing is None:
                continue
            finding_id = existing.id
            reopen = existing.status in repo.RESOLVED_STATUSES
            repo.mark_seen(
                db, finding_id, run_id=run_id, result_id=result_id, source_id=source_id,
                line_number=f.line, severity=f.severity, confidence=f.confidence, reopen=reopen,
            )  # fmt: skip
            if reopen:
                reopened += 1
                repo.insert_event(
                    db, finding_id, "reopened", from_value=existing.status, to_value="reopened",
                    detail={"run_id": str(run_id), "reason": "reported again by a later scan"},
                )  # fmt: skip
                _raise_reopened_alert(db, project_id, existing, run_id, result_id)
            else:
                seen += 1
                repo.insert_event(db, finding_id, "seen_again", detail={"run_id": str(run_id)})
        if report_artifact_id is not None and repo.link_evidence(
            db, finding_id, report_artifact_id, REPORT_NOTE
        ):
            repo.insert_event(
                db, finding_id, "evidence_added", detail={"artifact_id": str(report_artifact_id)}
            )
    fixed = 0
    if scan.complete and source_id is not None:
        fixed = _verify_absent(db, project_id, run_id, source_id, scan, report_artifact_id)
    dedup.regroup(db, project_id)  # link duplicates across tools; never merges or hides any
    return IngestSummary(created, seen, reopened, fixed)


def _verify_absent(
    db: Session,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    source_id: uuid.UUID,
    scan: ScanOutcome,
    report_artifact_id: uuid.UUID | None,
) -> int:
    count = 0
    seen = [f.fingerprint for f in scan.findings]
    for old in repo.unseen_open_findings(db, project_id, source_id, scan.tool, seen):
        target = "verified_fixed" if old.status == "fixed" else "fixed"
        note = (
            f"No longer reported by {scan.tool} in a complete scan of the same source. "
            "Absence from a static scan does not prove the weakness is gone."
        )
        repo.insert_attempt(
            db, finding_id=old.id, run_id=run_id, outcome="fixed", method="rescan",
            notes=note, evidence_artifact_id=report_artifact_id, created_by=None,
        )  # fmt: skip
        repo.insert_event(
            db, old.id, "verification_attempt", to_value="fixed",
            detail={"run_id": str(run_id), "method": "rescan"},
        )  # fmt: skip
        if repo.transition_status(db, old.id, old.status, target):
            repo.insert_event(
                db, old.id, "status_changed", from_value=old.status, to_value=target,
                detail={"run_id": str(run_id), "by": "rescan"},
            )  # fmt: skip
            count += 1
    return count


# ---- API side ---------------------------------------------------------------------------------


def _authorized(
    db: Session, ctx: RequestContext, user: UserRecord, finding_id: uuid.UUID, level: AccessLevel
) -> FindingRecord:
    finding = repo.get_finding(db, finding_id)
    if finding is None:
        raise DomainError(404, "not_found", "Finding not found")
    project_access_service.authorize_project(db, ctx, user, finding.project_id, level)
    return finding


def list_findings(
    db: Session, project_id: uuid.UUID, status: str | None, severity: str | None, limit: int
) -> list[FindingRecord]:
    return repo.list_findings(db, project_id, status=status, severity=severity, limit=limit)


def list_groups(db: Session, project_id: uuid.UUID, limit: int) -> list[repo.GroupRecord]:
    return repo.list_groups(db, project_id, limit)


def get_detail(
    db: Session, ctx: RequestContext, user: UserRecord, finding_id: uuid.UUID
) -> FindingDetail:
    finding = _authorized(db, ctx, user, finding_id, AccessLevel.READ)
    return FindingDetail(
        finding,
        repo.list_events(db, finding_id),
        repo.list_evidence(db, finding_id),
        repo.list_attempts(db, finding_id),
        [
            m
            for m in repo.group_members(db, finding.group_id, finding.project_id)
            if m.id != finding.id
        ]
        if finding.group_id
        else [],
    )


def _clean_note(note: str | None, *, required: bool) -> str | None:
    text = " ".join((note or "").split())
    if required and len(text) < MIN_NOTE:
        raise DomainError(
            422, "note_required", f"A note of at least {MIN_NOTE} characters is required"
        )
    return text[:MAX_NOTE] or None


def _deny(db: Session, ctx: RequestContext, user: UserRecord, f: FindingRecord, action: str, why: str) -> None:  # fmt: skip
    audit.record(
        db, ctx, action=action, outcome="denied", actor_user_id=user.id, project_id=f.project_id,
        target_type="finding", target_id=str(f.id), detail={"reason": why},
    )  # fmt: skip
    db.commit()


def change_status(
    db: Session,
    ctx: RequestContext,
    user: UserRecord,
    finding_id: uuid.UUID,
    to_status: str,
    note: str | None,
) -> FindingDetail:
    finding = _authorized(db, ctx, user, finding_id, AccessLevel.RUN)
    finding = repo.get_finding(db, finding_id, for_update=True) or finding
    if to_status not in MANUAL_TRANSITIONS.get(finding.status, frozenset()):
        _deny(db, ctx, user, finding, "finding.status", "transition_not_allowed")
        raise DomainError(
            409, "invalid_transition", f"A {finding.status} finding cannot be set to {to_status}"
        )
    if to_status in RISK_DECISIONS and not has_permission(
        user.role_name, Permission.FINDING_RISK_DECISION
    ):
        _deny(db, ctx, user, finding, "finding.status", "risk_decision_not_permitted")
        raise DomainError(
            403,
            "forbidden",
            "Marking a finding a false positive or accepting its risk needs an administrator",
        )
    clean = _clean_note(note, required=to_status in RISK_DECISIONS)
    if not repo.transition_status(db, finding_id, finding.status, to_status):
        raise DomainError(409, "conflict", "The finding changed; reload and try again")
    repo.insert_event(
        db, finding_id, "status_changed", from_value=finding.status, to_value=to_status,
        actor_user_id=user.id, detail={"note": clean} if clean else {},
    )  # fmt: skip
    audit.record(
        db, ctx, action="finding.status", outcome="success", actor_user_id=user.id,
        project_id=finding.project_id, target_type="finding", target_id=str(finding_id),
        detail={"from": finding.status, "to": to_status},
    )  # fmt: skip
    db.commit()
    return get_detail(db, ctx, user, finding_id)


def set_verification(
    db: Session,
    ctx: RequestContext,
    user: UserRecord,
    finding_id: uuid.UUID,
    state: str,
    note: str | None,
) -> FindingDetail:
    """A person's judgement about the finding. Never set by a scanner or a model."""
    finding = _authorized(db, ctx, user, finding_id, AccessLevel.RUN)
    if state not in MANUAL_VERIFICATION:
        raise DomainError(422, "invalid_state", "Unsupported verification state")
    clean = _clean_note(note, required=True)
    finding = repo.get_finding(db, finding_id, for_update=True) or finding
    if state == "confirmed" and not repo.list_evidence(db, finding_id):
        _deny(db, ctx, user, finding, "finding.verification", "no_evidence")
        raise DomainError(
            409, "evidence_required", "A finding cannot be confirmed without evidence"
        )
    repo.set_verification_state(db, finding_id, state)
    repo.insert_event(
        db, finding_id, "verification_changed", from_value=finding.verification_state,
        to_value=state, actor_user_id=user.id, detail={"note": clean},
    )  # fmt: skip
    audit.record(
        db, ctx, action="finding.verification", outcome="success", actor_user_id=user.id,
        project_id=finding.project_id, target_type="finding", target_id=str(finding_id),
        detail={"from": finding.verification_state, "to": state},
    )  # fmt: skip
    db.commit()
    return get_detail(db, ctx, user, finding_id)
