"""Deterministic alert rules, alert lifecycle and the telemetry disclosure (Stage 12, ADR-0011).

Rules are code with a version and fixed severity, title and next-action text. No model decides
whether to alert or how severe it is, and no text here claims a cause: an alert states what was
measured, when, where, and the evidence ids. ``cause_status`` stays ``not_investigated`` until a
person runs the investigation workflow on it.

One open alert exists per (project, rule, subject): repeats count occurrences instead of creating
more, and a project's open alerts are capped (the overflow is counted in one ``alert_overflow``
alert). Event rules run in the ingestion transaction for the touched groups, internal rules run
when a run finishes or a finding is reopened (best effort, never failing those transitions), and
time rules run lazily when alerts or telemetry are read."""

import logging
import statistics
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from sentinel_ai.core.config import Settings
from sentinel_ai.core.errors import DomainError
from sentinel_ai.repositories import observability as repo
from sentinel_ai.repositories.identity import UserRecord
from sentinel_ai.services import audit, observability_policy
from sentinel_ai.services.audit import RequestContext

logger = logging.getLogger(__name__)

RULE_VERSION = "alert-rules-v1"
SYSTEM = RequestContext(request_id=None, ip_address=None, user_agent=None)
MIN_BASELINE_BUCKETS = 6
DEFAULT_OPEN_CAP = 200  # used where no Settings object is at hand (run/finding hooks)
SEVERITY_BY_FINDING = {
    "info": "info",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "critical": "high",
}
AUDIT_ACTION = {"acknowledged": "alert.acknowledge", "resolved": "alert.resolve"}
INTERNAL_RULES = frozenset({"run_failed", "finding_reopened"})
MAX_RESULT_REFS = 20

NEXT_ACTIONS = {
    "new_error_group": "Open the group, read the redacted samples and stack, then investigate or reproduce the error before changing anything.",
    "error_rate_spike": "Compare the hour's count with the recent baseline, check what changed in that window (release, configuration, dependency), and read the samples.",
    "run_failed": "Open the run report and the failed results; the investigation workflow can suggest hypotheses from the stored evidence.",
    "finding_reopened": "Open the finding: a later scan reported it again after it was marked resolved. Review the evidence and the fix.",
    "telemetry_gap": "Check that the application and its log shipper still send events and that the ingest key is valid. No events is not the same as no errors.",
    "ingest_dropping": "Sentinel is refusing events (quota, rate limit or group cap), so counts are incomplete. Review the sender volume and the project limits.",
    "alert_overflow": "More alerts are open than the project cap. Acknowledge or resolve some; further alerts are only counted here.",
}
LIMITS = [
    "Sentinel resolves no trace ids, scrapes no metrics and keeps only grouped, redacted samples, not a raw log stream.",
    "Events below warning level and events from tools Sentinel does not receive from are not seen.",
    "External events are reported by the project's own application and can be wrong or forged; they never change a finding, run or verification state.",
    "Redaction is pattern based and can miss unknown secret shapes.",
]
CAUSE_NOTE = (
    "Sentinel measured the counts and times above. It does not know why this happened; "
    "no cause is claimed until it is investigated and verified."
)


def policy_thresholds(db: Session, project_id: uuid.UUID) -> tuple[bool, dict[str, float]]:
    return observability_policy.load(db, project_id)


# ---- raising alerts ---------------------------------------------------------------------------


def _open_exists(db: Session, project_id: uuid.UUID, rule: str, subject_key: str) -> bool:
    from sqlalchemy import text

    return (
        db.execute(
            text(
                "SELECT 1 FROM public.alerts WHERE project_id = :p AND rule = :r "
                "AND subject_key = :s AND status <> 'resolved'"
            ),
            {"p": project_id, "r": rule, "s": subject_key},
        ).first()
        is not None
    )


def raise_alert(
    db: Session, settings: Settings | None, project_id: uuid.UUID, *, rule: str, subject_key: str,
    severity: str, title: str, measured: dict[str, Any], evidence: dict[str, Any], now: datetime,
    group_id: uuid.UUID | None = None, run_id: uuid.UUID | None = None,
    result_id: uuid.UUID | None = None, finding_id: uuid.UUID | None = None,
) -> uuid.UUID:  # fmt: skip
    """Create or update the open alert for the subject, honouring the open-alert cap."""
    cap = settings.alert_open_cap if settings is not None else DEFAULT_OPEN_CAP
    if (
        rule != "alert_overflow"  # the overflow alert itself is always allowed
        and not _open_exists(db, project_id, rule, subject_key)
        and repo.open_alert_count(db, project_id) >= cap
    ):
        return raise_alert(
            db, settings, project_id, rule="alert_overflow", subject_key="project", severity="low",
            title="Alerts beyond the project cap are only counted",
            measured={"cap": cap, "last_suppressed_rule": rule},
            evidence={}, now=now,
        )  # fmt: skip
    alert_id, created = repo.upsert_alert(
        db, project_id=project_id, rule=rule, rule_version=RULE_VERSION, subject_key=subject_key,
        group_id=group_id, run_id=run_id, result_id=result_id, finding_id=finding_id,
        severity=severity, title=title[:200], measured=measured, evidence=evidence,
        next_action=NEXT_ACTIONS[rule], now=now,
    )  # fmt: skip
    if created:
        repo.add_history(
            db, alert_id=alert_id, project_id=project_id, action="created", actor_user_id=None,
            detail={"rule": rule, "rule_version": RULE_VERSION},
        )  # fmt: skip
        audit.record(
            db, SYSTEM, action="alert.create", outcome="success", actor_type="system",
            project_id=project_id, target_type="alert", target_id=str(alert_id),
            detail={"rule": rule, "severity": severity},
        )  # fmt: skip
    return alert_id


def evaluate_groups(
    db: Session, project_id: uuid.UUID, groups: list[dict[str, Any]], now: datetime,
    th: dict[str, float], settings: Settings,
) -> None:  # fmt: skip
    """Event rules for the groups a batch touched (error and fatal levels only)."""
    for touched in groups:
        if touched["level_class"] not in ("error", "fatal"):
            continue
        group = repo.get_group(db, project_id, touched["id"])
        if group is None or group["is_overflow"]:
            continue
        gid = group["id"]
        where = {"service": group["service"], "environment": group["environment"],
                 "error_type": group["error_type"]}  # fmt: skip
        reopened = None
        if not touched.get("inserted"):
            reopened = repo.reopen_for_group(db, project_id, gid)
            if reopened is not None:
                repo.add_history(
                    db, alert_id=reopened["id"], project_id=project_id, action="reopened",
                    actor_user_id=None,
                    detail={"rule": "recurrence", "events_total": group["total_count"]},
                )  # fmt: skip
                audit.record(
                    db, SYSTEM, action="alert.reopen", outcome="success", actor_type="system",
                    project_id=project_id, target_type="alert", target_id=str(reopened["id"]),
                    detail={"rule": "recurrence"},
                )  # fmt: skip
        needed = 1 if group["level_class"] == "fatal" else int(th["new_group_events"])
        window = timedelta(minutes=th["new_group_window_minutes"])
        if (
            reopened is None
            and now - group["first_seen"] <= window
            and group["total_count"] >= needed
        ):
            raise_alert(
                db, settings, project_id, rule="new_error_group", subject_key=f"group:{gid}",
                severity="high" if group["level_class"] == "fatal" else "medium",
                title=f"New {group['level_class']} group in {group['service']}",
                measured={"events": group["total_count"], "first_seen": group["first_seen"].isoformat(),
                          "window_minutes": th["new_group_window_minutes"], **where},
                evidence={"group_id": str(gid)}, now=now, group_id=gid,
            )  # fmt: skip
        current, prior = repo.window_counts(db, gid, now)
        baseline = len(prior) >= MIN_BASELINE_BUCKETS
        median = statistics.median(prior) if baseline else None
        if current >= th["spike_min_events"] and (
            not baseline or current >= th["spike_ratio"] * float(median or 0)
        ):
            raise_alert(
                db, settings, project_id, rule="error_rate_spike", subject_key=f"group:{gid}",
                severity="medium", title=f"Error rate spike in {group['service']}",
                measured={"events_this_hour": current, "baseline_available": baseline,
                          "median_previous_hours": median, "ratio_threshold": th["spike_ratio"],
                          "min_events": th["spike_min_events"], **where},
                evidence={"group_id": str(gid)}, now=now, group_id=gid,
            )  # fmt: skip


def evaluate_run(
    db: Session, settings: Settings | None, run_id: uuid.UUID, now: datetime | None = None
) -> None:
    """Internal rule: a run ended failed/timed out, or produced failed/errored/timed-out results.
    Derived from rows Sentinel already holds; no log text is copied."""
    from sqlalchemy import text

    now = now or datetime.now(UTC)
    run = db.execute(
        text("SELECT id, project_id, status, error_code FROM public.test_runs WHERE id = :r"),
        {"r": run_id},
    ).first()
    if run is None or run.status in (
        "queued",
        "dispatched",
        "running",
        "cancel_requested",
        "cancelled",
    ):
        return
    failed = repo.failed_results_of_run(db, run_id, MAX_RESULT_REFS)
    if run.status == "completed" and not failed:
        return
    statuses = {str(f["status"]) for f in failed}
    severity = "medium" if run.status == "failed" or "failed" in statuses else "low"
    raise_alert(
        db, settings, run.project_id, rule="run_failed", subject_key=f"run:{run_id}",
        severity=severity, title="A test run ended with failures",
        measured={"run_status": run.status, "error_code": run.error_code, "failed_results": len(failed),
                  "result_statuses": sorted(statuses)},
        evidence={"run_id": str(run_id), "result_ids": [str(f["id"]) for f in failed]},
        now=now, run_id=run_id, result_id=failed[0]["id"] if failed else None,
    )  # fmt: skip


def finding_reopened(
    db: Session, settings: Settings | None, project_id: uuid.UUID, finding_id: uuid.UUID, *, title: str,
    severity: str, run_id: uuid.UUID, result_id: uuid.UUID,
) -> None:  # fmt: skip
    raise_alert(
        db, settings, project_id, rule="finding_reopened", subject_key=f"finding:{finding_id}",
        severity=SEVERITY_BY_FINDING.get(severity, "medium"), title=f"Finding reopened: {title}"[:200],
        measured={"finding_severity": severity},
        evidence={"finding_id": str(finding_id), "run_id": str(run_id), "result_id": str(result_id)},
        now=datetime.now(UTC), run_id=run_id, result_id=result_id, finding_id=finding_id,
    )  # fmt: skip


def raise_ingest_dropping(
    db: Session, project_id: uuid.UUID, dropped: Any, now: datetime, settings: Settings
) -> None:
    raise_alert(
        db, settings, project_id, rule="ingest_dropping", subject_key="project", severity="low",
        title="Sentinel is dropping events",
        measured={k: int(v) for k, v in dropped.items() if v}, evidence={}, now=now,
    )  # fmt: skip


def close_gap_alert(db: Session, project_id: uuid.UUID) -> None:
    """Events resumed: a silence alert no longer applies (closed by the system, with history)."""
    from sqlalchemy import text

    row = db.execute(
        text(
            "UPDATE public.alerts SET status = 'resolved', closed_at = now() WHERE project_id = :p "
            "AND rule = 'telemetry_gap' AND status <> 'resolved' RETURNING id"
        ),
        {"p": project_id},
    ).first()
    if row is not None:
        repo.add_history(
            db, alert_id=row.id, project_id=project_id, action="resolved", actor_user_id=None,
            note="Events resumed.", detail={"by": "system"},
        )  # fmt: skip


def evaluate_time_rules(
    db: Session, settings: Settings, project_id: uuid.UUID, now: datetime
) -> None:
    """Lazy, idempotent evaluation of rules driven by the absence of events."""
    enabled, th = policy_thresholds(db, project_id)
    if not enabled:
        return
    repo.project_lock(db, project_id)
    since_day = (now - timedelta(days=7)).date()
    active = sum(int(r["accepted"]) for r in repo.stats_since(db, project_id, since_day))
    last = repo.last_event_time(db, project_id)
    if active and last is not None and now - last >= timedelta(hours=th["gap_silence_hours"]):
        raise_alert(
            db, settings, project_id, rule="telemetry_gap", subject_key="project", severity="info",
            title="No events received for a while",
            measured={"last_event_at": last.isoformat(), "silence_hours": th["gap_silence_hours"],
                      "events_last_7_days": active},
            evidence={}, now=now,
        )  # fmt: skip


def safe_time_rules(
    db: Session, settings: Settings, project_id: uuid.UUID, now: datetime | None = None
) -> None:
    """Run the time rules; a failure is counted and logged, never raised to the reader."""
    now = now or datetime.now(UTC)
    try:
        with db.begin_nested():
            evaluate_time_rules(db, settings, project_id, now)
    except Exception as exc:
        logger.warning("alert time rules failed (%s)", type(exc).__name__)
        repo.add_stats(db, project_id, now.date(), accepted=0, dropped={}, eval_errors=1)


# ---- reading and lifecycle ----------------------------------------------------------------------


def alert_view(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "source": "internal" if row["rule"] in INTERNAL_RULES else "external"}


def list_alerts(
    db: Session, settings: Settings, project_id: uuid.UUID, *, status: str | None,
    severity: str | None, rule: str | None, limit: int, offset: int,
) -> list[dict[str, Any]]:  # fmt: skip
    safe_time_rules(db, settings, project_id)
    rows = repo.list_alerts(
        db, project_id, status=status, severity=severity, rule=rule, limit=limit, offset=offset
    )
    return [alert_view(r) for r in rows]


def get_alert(db: Session, project_id: uuid.UUID, alert_id: uuid.UUID) -> dict[str, Any]:
    row = repo.get_alert(db, project_id, alert_id)  # scoped: an id alone is nothing
    if row is None:
        raise DomainError(404, "not_found", "Alert not found")
    return alert_view(row)


def alert_detail(
    db: Session, settings: Settings, project_id: uuid.UUID, alert_id: uuid.UUID
) -> dict[str, Any]:
    safe_time_rules(db, settings, project_id)
    alert = get_alert(db, project_id, alert_id)
    group = repo.get_group(db, project_id, alert["group_id"]) if alert["group_id"] else None
    return {
        **alert,
        "history": repo.list_history(db, alert_id),
        "group": group_view(group) if group else None,
        "proposal_ids": repo.proposals_for_alert(db, project_id, alert_id),
        "telemetry": telemetry_status(db, project_id, datetime.now(UTC)),
        "cause_note": CAUSE_NOTE,
    }


def group_view(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "message": row["message_norm"], "fingerprint_version": row["fp_version"]}


def _note(note: str | None) -> str | None:
    cleaned = " ".join(note.split()) if note else None
    if cleaned and len(cleaned) > 1000:
        raise DomainError(422, "validation_failed", "note must be at most 1000 characters")
    return cleaned or None


def _change(
    db: Session, ctx: RequestContext, user: UserRecord, project_id: uuid.UUID, alert_id: uuid.UUID,
    *, to: str, allowed_from: tuple[str, ...], action: str, note: str | None,
) -> dict[str, Any]:  # fmt: skip
    current = get_alert(db, project_id, alert_id)
    if not repo.transition_alert(db, project_id, alert_id, to=to, from_statuses=allowed_from):
        raise DomainError(409, "invalid_state", f"This alert is already {current['status']}")
    cleaned = _note(note)
    repo.add_history(
        db, alert_id=alert_id, project_id=project_id, action=action, actor_user_id=user.id,
        note=cleaned, detail={"from": current["status"]},
    )  # fmt: skip
    audit.record(
        db, ctx, action=AUDIT_ACTION[action],
        outcome="success", actor_user_id=user.id, project_id=project_id, target_type="alert",
        target_id=str(alert_id), detail={"rule": current["rule"], "from": current["status"]},
    )  # fmt: skip
    return get_alert(db, project_id, alert_id)


def acknowledge(
    db: Session,
    ctx: RequestContext,
    user: UserRecord,
    project_id: uuid.UUID,
    alert_id: uuid.UUID,
    note: str | None,
) -> dict[str, Any]:
    return _change(db, ctx, user, project_id, alert_id, to="acknowledged",
                   allowed_from=("open",), action="acknowledged", note=note)  # fmt: skip


def resolve(
    db: Session,
    ctx: RequestContext,
    user: UserRecord,
    project_id: uuid.UUID,
    alert_id: uuid.UUID,
    note: str | None,
) -> dict[str, Any]:
    return _change(db, ctx, user, project_id, alert_id, to="resolved",
                   allowed_from=("open", "acknowledged"), action="resolved", note=note)  # fmt: skip


def link_investigation(
    db: Session,
    ctx: RequestContext,
    user: UserRecord,
    project_id: uuid.UUID,
    alert_id: uuid.UUID,
    run_id: uuid.UUID,
    action: str,
) -> None:
    """Record that a person ran the investigation or regression workflow on this alert."""
    if action == "alert.investigate":
        repo.set_investigation(db, project_id, alert_id, run_id)
        repo.add_history(
            db, alert_id=alert_id, project_id=project_id, action="investigated",
            actor_user_id=user.id, detail={"agent_run_id": str(run_id)},
        )  # fmt: skip
    audit.record(
        db, ctx, action=action, outcome="success", actor_user_id=user.id, project_id=project_id,
        target_type="alert", target_id=str(alert_id), detail={"agent_run_id": str(run_id)},
    )  # fmt: skip


# ---- groups and telemetry ----------------------------------------------------------------------


def telemetry_status(db: Session, project_id: uuid.UUID, now: datetime) -> dict[str, Any]:
    """Facts about what was received, built only from stored rows, plus fixed text on what
    Stage 12 cannot see. A project with no events says so."""
    from sentinel_ai.repositories import policies

    rows = policies.project_rows(db, project_id)
    since = now - timedelta(hours=24)
    last = repo.last_event_time(db, project_id)
    stats = repo.stats_since(db, project_id, (now - timedelta(days=1)).date())
    dropped: dict[str, int] = {}
    errors = 0
    for s in stats:
        errors += int(s["eval_errors"])
        for reason, n in (s["dropped"] or {}).items():
            dropped[reason] = dropped.get(reason, 0) + int(n)
    counts = repo.telemetry_counts(db, project_id, since)
    groups = max(counts["groups"], 1)
    return {
        "ingest_enabled": observability_policy.ingest_enabled(rows),
        "active_keys": repo.count_active_keys(db, project_id),
        "has_events": last is not None,
        "last_event_at": last,
        "events_last_24h_by_level": counts["levels"],
        "events_last_24h_by_environment": counts["environments"],
        "dropped_last_24h": dropped,
        "evaluation_errors_last_24h": errors,
        "groups": counts["groups"],
        "share_of_groups_with_stack": round(counts["groups_with_stack"] / groups, 2),
        "samples_with_trace_id": counts["samples_with_trace_id"],
        "samples_with_verified_link": counts["samples_with_verified_link"],
        "summary": (
            "No application events have been received." if last is None else
            "Events were received; see the counts below and the limits."
        ),
        "limits": LIMITS,
    }  # fmt: skip


def list_groups(
    db: Session, project_id: uuid.UUID, limit: int, offset: int
) -> list[dict[str, Any]]:
    return [group_view(g) for g in repo.list_groups(db, project_id, limit, offset)]


def group_detail(
    db: Session, settings: Settings, project_id: uuid.UUID, group_id: uuid.UUID
) -> dict[str, Any]:
    group = repo.get_group(db, project_id, group_id)
    if group is None:
        raise DomainError(404, "not_found", "Event group not found")
    since = datetime.now(UTC) - timedelta(days=settings.event_sample_retention_days)
    samples = repo.list_samples(db, project_id, group_id, settings.event_samples_per_group, since)
    return {**group_view(group), "samples": samples, "limits": LIMITS}
