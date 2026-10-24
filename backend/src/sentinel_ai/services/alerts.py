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
INTERNAL_RULES = frozenset(
    {"run_failed", "finding_reopened", "llm_cost_spike", "llm_runaway", "llm_error_rate",
     "run_duration_anomaly"}
)  # fmt: skip
MAX_RESULT_REFS = 20
MIN_MODEL_CALLS_FOR_ERROR_RATE = 5
RUNAWAY_CALLS_PER_RUN = 12  # model attempts inside one workflow run
MIN_BASELINE_DAYS = 3
MIN_BASELINE_RUNS = 3
MIN_ANOMALY_SECONDS = 30.0

NEXT_ACTIONS = {
    "new_error_group": "Open the group, read the redacted samples and stack, then investigate or reproduce the error before changing anything.",
    "error_rate_spike": "Compare the hour's count with the recent baseline, check what changed in that window (release, configuration, dependency), and read the samples.",
    "run_failed": "Open the run report and the failed results; the investigation workflow can suggest hypotheses from the stored evidence.",
    "finding_reopened": "Open the finding: a later scan reported it again after it was marked resolved. Review the evidence and the fix.",
    "telemetry_gap": "Check that the application and its log shipper still send events and that the ingest key is valid. No events is not the same as no errors.",
    "ingest_dropping": "Sentinel is refusing events (quota, rate limit or group cap), so counts are incomplete. Review the sender volume and the project limits.",
    "llm_cost_spike": "Open the assistant runs of the last day, check for loops or unusually large evidence, and compare the estimated cost with your budget. The figure is an estimate (tokens times configured prices).",
    "llm_runaway": "Look at the assistant runs started in the last hour: a script, a retry loop or repeated requests may be starting workflows. Budgets still apply to every call.",
    "llm_error_rate": "Check the model configuration, the provider status and the budget limits; failed calls degrade assistant results but never change a finding or a run.",
    "run_duration_anomaly": "Open the run and compare its checks with earlier runs of the same plan; a longer run can mean more work, a slower environment or a stuck check. It is a measurement, not a verdict.",
    "alert_overflow": "More alerts are open than the project cap. Acknowledge or resolve some; further alerts are only counted here.",
}
LIMITS = [
    "Sentinel resolves no trace ids, scrapes no metrics and keeps only grouped, redacted samples, not a raw log stream.",
    "Events below warning level and events from tools Sentinel does not receive from are not seen.",
    "External events are reported by the project's own application and can be wrong or forged; they never change a finding, run or verification state.",
    "Redaction is pattern based and can miss unknown secret shapes.",
    "Resource figures are limited to run durations and model usage; CPU and memory of target applications are not measured, and model costs are estimates (tokens times configured prices).",
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


def _group_title(prefix: str, group: dict[str, Any]) -> str:
    """A title that tells alerts apart: the error type and the message pattern (already
    redacted and normalized), cut to fit. A measurement, not a cause."""
    what = " ".join(x for x in (group["error_type"], group["message_norm"]) if x)
    return f"{prefix}: {what}"[:200]


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
                title=_group_title(f"New {group['level_class']} in {group['service']}", group),
                measured={"events": group["total_count"], "first_seen": group["first_seen"].isoformat(),
                          "window_minutes": th["new_group_window_minutes"], **where},
                evidence={"group_id": str(gid)}, now=now, group_id=gid,
            )  # fmt: skip
        current, prior = repo.window_counts(db, gid, now)
        baseline = len(prior) >= MIN_BASELINE_BUCKETS
        median = statistics.median(prior) if baseline else None
        if not baseline and now - group["first_seen"] <= window:
            continue  # a brand-new group is already covered by new_error_group: one alert, not two
        if current >= th["spike_min_events"] and (
            not baseline or current >= th["spike_ratio"] * float(median or 0)
        ):
            raise_alert(
                db, settings, project_id, rule="error_rate_spike", subject_key=f"group:{gid}",
                severity="medium", title=_group_title(f"Error rate spike in {group['service']}", group),
                measured={"events_this_hour": current, "baseline_available": baseline,
                          "median_previous_hours": median, "ratio_threshold": th["spike_ratio"],
                          "min_events": th["spike_min_events"], **where},
                evidence={"group_id": str(gid)}, now=now, group_id=gid,
            )  # fmt: skip


def evaluate_run(
    db: Session, settings: Settings | None, run_id: uuid.UUID, now: datetime | None = None
) -> None:
    """Internal rules for a finished run: it ended failed/timed out or produced failed, errored
    or timed-out results (``run_failed``), or a completed run took far longer than earlier runs
    of the same plan (``run_duration_anomaly``). Derived from rows Sentinel already holds; no
    log text is copied."""
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
    if run.status != "completed" or failed:
        statuses = {str(f["status"]) for f in failed}
        severity = "medium" if run.status == "failed" or "failed" in statuses else "low"
        raise_alert(
            db, settings, run.project_id, rule="run_failed", subject_key=f"run:{run_id}",
            severity=severity, title="A test run ended with failures",
            measured={"run_status": run.status, "error_code": run.error_code,
                      "failed_results": len(failed), "result_statuses": sorted(statuses)},
            evidence={"run_id": str(run_id), "result_ids": [str(f["id"]) for f in failed]},
            now=now, run_id=run_id, result_id=failed[0]["id"] if failed else None,
        )  # fmt: skip
    if run.status == "completed":
        _duration_anomaly(db, settings, run.project_id, run_id, now)


def _duration_anomaly(
    db: Session, settings: Settings | None, project_id: uuid.UUID, run_id: uuid.UUID, now: datetime
) -> None:
    timing = repo.run_duration_seconds(db, run_id)
    if timing is None or timing[1] is None:
        return
    plan_id = timing[0]
    seconds: float = timing[1]
    prior = repo.previous_run_durations(db, plan_id, run_id, 10)
    if len(prior) < MIN_BASELINE_RUNS or seconds < MIN_ANOMALY_SECONDS:
        return
    median = statistics.median(prior)
    _, th = policy_thresholds(db, project_id)
    if median > 0 and seconds >= th["run_duration_ratio"] * median:
        raise_alert(
            db, settings, project_id, rule="run_duration_anomaly", subject_key=f"run:{run_id}",
            severity="low", title="A run took much longer than earlier runs of the same plan",
            measured={"duration_seconds": round(seconds, 1), "median_previous_seconds": round(median, 1),
                      "previous_runs_compared": len(prior), "ratio_threshold": th["run_duration_ratio"]},
            evidence={"run_id": str(run_id), "plan_id": str(plan_id)}, now=now, run_id=run_id,
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
    """Lazy, idempotent evaluation of rules that are not triggered by one event: silence after
    activity (only where ingestion is on) and the deterministic model-cost and resource rules."""
    enabled, th = policy_thresholds(db, project_id)
    repo.project_lock(db, project_id)
    if enabled:
        since_day = (now - timedelta(days=7)).date()
        active = sum(int(r["accepted"]) for r in repo.stats_since(db, project_id, since_day))
        last = repo.last_event_time(db, project_id)
        if active and last is not None and now - last >= timedelta(hours=th["gap_silence_hours"]):
            raise_alert(
                db, settings, project_id, rule="telemetry_gap", subject_key="project",
                severity="info", title="No events received for a while",
                measured={"last_event_at": last.isoformat(),
                          "silence_hours": th["gap_silence_hours"], "events_last_7_days": active},
                evidence={}, now=now,
            )  # fmt: skip
    evaluate_model_rules(db, settings, project_id, now, th)


def evaluate_model_rules(
    db: Session, settings: Settings, project_id: uuid.UUID, now: datetime, th: dict[str, float]
) -> None:
    """Cost and resource anomalies from ``llm_usage`` and ``agent_runs`` (deterministic rules;
    every figure is an estimate, and calls that are still reserved are counted as incomplete)."""
    day = repo.usage_totals(db, project_id, now - timedelta(hours=24))
    cost = float(day["cost"])
    prior = repo.daily_cost(db, project_id, now - timedelta(days=8), now - timedelta(hours=24))
    baseline = len(prior) >= MIN_BASELINE_DAYS
    median = statistics.median(prior) if baseline else None
    if cost >= th["cost_spike_min_usd"] and (
        not baseline or cost >= th["cost_spike_ratio"] * float(median or 0)
    ):
        raise_alert(
            db, settings, project_id, rule="llm_cost_spike", subject_key="project",
            severity="medium", title="Estimated model cost is unusually high",
            measured={"estimated_cost_usd_24h": round(cost, 4), "cost_is_estimate": True,
                      "baseline_available": baseline,
                      "median_daily_estimated_cost_usd": round(median, 4) if median is not None else None,
                      "ratio_threshold": th["cost_spike_ratio"], "min_usd": th["cost_spike_min_usd"],
                      "unsettled_calls": int(day["unsettled"])},
            evidence={}, now=now,
        )  # fmt: skip
    hour = repo.usage_totals(db, project_id, now - timedelta(hours=1))
    runs = repo.agent_run_counts(db, project_id, now - timedelta(hours=1))
    if (
        int(runs["runs"]) >= th["runaway_runs_per_hour"]
        or int(runs["max_calls_one_run"]) >= RUNAWAY_CALLS_PER_RUN
    ):
        raise_alert(
            db, settings, project_id, rule="llm_runaway", subject_key="project", severity="medium",
            title="Assistant workflows are running unusually often or retrying a lot",
            measured={"assistant_runs_last_hour": int(runs["runs"]),
                      "most_model_attempts_in_one_run": int(runs["max_calls_one_run"]),
                      "runs_threshold": th["runaway_runs_per_hour"],
                      "attempts_per_run_threshold": RUNAWAY_CALLS_PER_RUN},
            evidence={}, now=now,
        )  # fmt: skip
    settled = int(hour["ok"]) + int(hour["failed"])
    if settled >= MIN_MODEL_CALLS_FOR_ERROR_RATE:
        rate = 100.0 * int(hour["failed"]) / settled
        if rate >= th["llm_error_rate_percent"]:
            raise_alert(
                db, settings, project_id, rule="llm_error_rate", subject_key="project",
                severity="medium", title="Many model calls are failing",
                measured={"failed_calls_last_hour": int(hour["failed"]), "settled_calls_last_hour": settled,
                          "failure_percent": round(rate, 1), "threshold_percent": th["llm_error_rate_percent"],
                          "blocked_by_budget": int(hour["blocked"])},
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


def evaluate_scheduled(
    session_factory: Any, settings: Settings, now: datetime | None = None
) -> tuple[int, int]:
    """Run the time-driven rules for every project that needs them (called by the scheduled job
    and ``cli evaluate-alerts``). One project's failure never stops the others. Returns
    (projects evaluated, projects that failed)."""
    with session_factory() as db:
        ids = repo.projects_for_scheduled_rules(db)
    done = failed = 0
    for project_id in ids:
        try:
            with session_factory() as db:
                evaluate_time_rules(db, settings, project_id, now or datetime.now(UTC))
                db.commit()
            done += 1
        except Exception as exc:
            failed += 1
            logger.warning(
                "scheduled alert evaluation failed for one project (%s)", type(exc).__name__
            )
    return done, failed


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
    usage = repo.usage_totals(db, project_id, since)
    steps = repo.agent_step_counts(db, project_id, since)
    runs = repo.agent_run_counts(db, project_id, since)
    global_rows = policies.global_rows(db)
    return {
        "thresholds": observability_policy.thresholds(rows, global_rows),
        "threshold_bounds": {
            k: list(v) for k, v in observability_policy.effective_bounds(global_rows).items()
        },
        "model_usage": {
            "window_hours": 24,
            "calls": int(usage["calls"]), "ok": int(usage["ok"]), "failed": int(usage["failed"]),
            "blocked_by_budget": int(usage["blocked"]), "retries": int(usage["retries"]),
            "input_tokens": int(usage["input_tokens"]), "output_tokens": int(usage["output_tokens"]),
            "estimated_cost_usd": round(float(usage["cost"]), 4), "cost_is_estimate": True,
            "average_latency_ms": round(float(usage["avg_latency_ms"])),
            "max_latency_ms": int(usage["max_latency_ms"]),
            "incomplete_calls": int(usage["unsettled"]) + int(usage["no_latency"]),
            "assistant_runs": int(runs["runs"]), "workflow_steps": int(steps["steps"]),
            "model_steps": int(steps["model_steps"]),
            "note": "Costs are estimates (tokens reported by the provider times the configured "
                    "prices); calls still reserved or without a latency are counted as incomplete.",
        },
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
