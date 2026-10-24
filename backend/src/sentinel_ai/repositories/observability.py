"""SQL for ingest keys, event groups/buckets/samples, alerts and their history (Stage 12,
ADR-0011). Every query that reads a child row is scoped by ``project_id``: an id alone is never
proof of access. Rows are returned as plain dicts of column values."""

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

Row = dict[str, Any]

_ALERT_COLS = (
    "id, project_id, rule, rule_version, subject_key, group_id, run_id, result_id, finding_id, "
    "severity, status, title, measured, evidence, next_action, occurrences, cause_status, "
    "agent_run_id, first_seen, last_seen, closed_at, created_at, updated_at"
)
_GROUP_COLS = (
    "id, project_id, fingerprint, fp_version, service, environment, level_class, error_type, "
    "message_norm, first_seen, last_seen, total_count, has_stack, is_overflow"
)
_SAMPLE_COLS = (
    "id, group_id, received_at, client_timestamp, timestamp_untrusted, level, service, "
    "environment, message, error_type, stack, attributes, trace_id, span_id, release, claimed, "
    "correlation, redactions"
)
_KEY_COLS = (
    "id, project_id, key_id, label, created_by, created_at, expires_at, revoked_at, last_used_at"
)


def _rows(result: Any) -> list[Row]:
    return [dict(r._mapping) for r in result.all()]


def _one(result: Any) -> Row | None:
    row = result.first()
    return dict(row._mapping) if row else None


# ---- ingest keys ---------------------------------------------------------------------------


def insert_key(
    db: Session, *, project_id: uuid.UUID, key_id: str, key_hash: bytes, label: str,
    created_by: uuid.UUID, expires_at: datetime,
) -> Row:  # fmt: skip
    return _one(  # type: ignore[return-value]
        db.execute(
            text(
                "INSERT INTO public.ingest_keys (project_id, key_id, key_hash, label, created_by, "
                f"expires_at) VALUES (:p, :k, :h, :l, :u, :e) RETURNING {_KEY_COLS}"
            ),
            {
                "p": project_id,
                "k": key_id,
                "h": key_hash,
                "l": label,
                "u": created_by,
                "e": expires_at,
            },
        )
    )


def list_keys(db: Session, project_id: uuid.UUID) -> list[Row]:
    return _rows(
        db.execute(
            text(
                f"SELECT {_KEY_COLS} FROM public.ingest_keys WHERE project_id = :p "
                "ORDER BY created_at DESC, id"
            ),
            {"p": project_id},
        )
    )


def count_active_keys(db: Session, project_id: uuid.UUID) -> int:
    row = db.execute(
        text(
            "SELECT count(*) AS n FROM public.ingest_keys WHERE project_id = :p "
            "AND revoked_at IS NULL AND expires_at > now()"
        ),
        {"p": project_id},
    ).one()
    return int(row.n)


def get_key_for_auth(db: Session, key_id: str) -> Row | None:
    return _one(
        db.execute(
            text(
                "SELECT k.id, k.project_id, k.key_hash, k.expires_at, k.revoked_at, "
                "p.archived_at FROM public.ingest_keys k JOIN public.projects p "
                "ON p.id = k.project_id WHERE k.key_id = :k"
            ),
            {"k": key_id},
        )
    )


def revoke_key(db: Session, project_id: uuid.UUID, key_row_id: uuid.UUID) -> Row | None:
    return _one(
        db.execute(
            text(
                "UPDATE public.ingest_keys SET revoked_at = now() WHERE id = :i AND project_id = :p "
                f"AND revoked_at IS NULL RETURNING {_KEY_COLS}"
            ),
            {"i": key_row_id, "p": project_id},
        )
    )


def get_key(db: Session, project_id: uuid.UUID, key_row_id: uuid.UUID) -> Row | None:
    return _one(
        db.execute(
            text(f"SELECT {_KEY_COLS} FROM public.ingest_keys WHERE id = :i AND project_id = :p"),
            {"i": key_row_id, "p": project_id},
        )
    )


def touch_key(db: Session, key_row_id: uuid.UUID) -> None:
    db.execute(
        text(
            "UPDATE public.ingest_keys SET last_used_at = now() WHERE id = :i "
            "AND (last_used_at IS NULL OR last_used_at < now() - interval '1 minute')"
        ),
        {"i": key_row_id},
    )


# ---- groups, buckets, samples --------------------------------------------------------------


def count_groups(db: Session, project_id: uuid.UUID) -> int:
    row = db.execute(
        text("SELECT count(*) AS n FROM public.event_groups WHERE project_id = :p"),
        {"p": project_id},
    ).one()
    return int(row.n)


def group_exists(db: Session, project_id: uuid.UUID, fingerprint: str) -> bool:
    return (
        db.execute(
            text("SELECT 1 FROM public.event_groups WHERE project_id = :p AND fingerprint = :f"),
            {"p": project_id, "f": fingerprint},
        ).first()
        is not None
    )


def upsert_group(
    db: Session, *, project_id: uuid.UUID, fingerprint: str, fp_version: str, service: str,
    environment: str, level_class: str, error_type: str | None, message_norm: str,
    has_stack: bool, is_overflow: bool, now: datetime,
) -> Row:  # fmt: skip
    return _one(  # type: ignore[return-value]
        db.execute(
            text(
                "INSERT INTO public.event_groups (project_id, fingerprint, fp_version, service, "
                "environment, level_class, error_type, message_norm, first_seen, last_seen, "
                "has_stack, is_overflow) VALUES (:p, :f, :v, :s, :env, :lc, :et, :m, :now, :now, "
                ":hs, :ov) ON CONFLICT (project_id, fingerprint) DO UPDATE SET "
                "last_seen = GREATEST(public.event_groups.last_seen, EXCLUDED.last_seen), "
                "total_count = public.event_groups.total_count + 1, "
                "has_stack = public.event_groups.has_stack OR EXCLUDED.has_stack "
                "RETURNING id, total_count, first_seen, last_seen, level_class, (xmax = 0) AS inserted"
            ),
            {"p": project_id, "f": fingerprint, "v": fp_version, "s": service, "env": environment,
             "lc": level_class, "et": error_type, "m": message_norm, "now": now, "hs": has_stack,
             "ov": is_overflow},
        )
    )  # fmt: skip


def bump_bucket(db: Session, group_id: uuid.UUID, bucket_start: datetime) -> None:
    db.execute(
        text(
            "INSERT INTO public.event_buckets (group_id, bucket_start, count) VALUES (:g, :b, 1) "
            "ON CONFLICT (group_id, bucket_start) DO UPDATE SET "
            "count = public.event_buckets.count + 1"
        ),
        {"g": group_id, "b": bucket_start},
    )


def insert_sample(db: Session, *, project_id: uuid.UUID, group_id: uuid.UUID, key_row_id: uuid.UUID,
                  received_at: datetime, e: dict[str, Any]) -> None:  # fmt: skip
    db.execute(
        text(
            "INSERT INTO public.events (project_id, group_id, key_id, event_id, received_at, "
            "client_timestamp, timestamp_untrusted, level, service, environment, message, "
            "error_type, stack, attributes, trace_id, span_id, release, claimed, correlation, "
            "redactions) VALUES (:p, :g, :k, :eid, :ra, :ct, :tu, :lv, :sv, :env, :msg, :et, "
            ":st, CAST(:attr AS jsonb), :tr, :sp, :rel, CAST(:cl AS jsonb), CAST(:co AS jsonb), "
            "CAST(:rd AS jsonb))"
        ),
        {"p": project_id, "g": group_id, "k": key_row_id, "eid": e.get("event_id"), "ra": received_at,
         "ct": e.get("client_timestamp"), "tu": e["timestamp_untrusted"], "lv": e["level"],
         "sv": e["service"], "env": e["environment"], "msg": e["message"], "et": e.get("error_type"),
         "st": e.get("stack"), "attr": json.dumps(e["attributes"]), "tr": e.get("trace_id"),
         "sp": e.get("span_id"), "rel": e.get("release"), "cl": json.dumps(e["claimed"]),
         "co": json.dumps(e["correlation"]), "rd": json.dumps(e["redactions"])},
    )  # fmt: skip


def trim_samples(db: Session, group_id: uuid.UUID, keep_first: int, keep_total: int) -> None:
    """Keep the first ``keep_first`` samples and the most recent ``keep_total - keep_first``."""
    db.execute(
        text(
            "DELETE FROM public.events WHERE group_id = :g AND id NOT IN ("
            "(SELECT id FROM public.events WHERE group_id = :g ORDER BY received_at, seq LIMIT :f) "
            "UNION (SELECT id FROM public.events WHERE group_id = :g "
            "ORDER BY received_at DESC, seq DESC LIMIT :r))"
        ),
        {"g": group_id, "f": keep_first, "r": keep_total - keep_first},
    )


def get_group(db: Session, project_id: uuid.UUID, group_id: uuid.UUID) -> Row | None:
    return _one(
        db.execute(
            text(
                f"SELECT {_GROUP_COLS} FROM public.event_groups WHERE id = :i AND project_id = :p"
            ),
            {"i": group_id, "p": project_id},
        )
    )


def list_groups(db: Session, project_id: uuid.UUID, limit: int, offset: int) -> list[Row]:
    return _rows(
        db.execute(
            text(
                f"SELECT {_GROUP_COLS} FROM public.event_groups WHERE project_id = :p "
                "ORDER BY last_seen DESC, id LIMIT :n OFFSET :o"
            ),
            {"p": project_id, "n": limit, "o": offset},
        )
    )


def list_samples(
    db: Session, project_id: uuid.UUID, group_id: uuid.UUID, limit: int, since: datetime
) -> list[Row]:
    return _rows(
        db.execute(
            text(
                f"SELECT {_SAMPLE_COLS} FROM public.events WHERE project_id = :p AND group_id = :g "
                "AND received_at >= :since ORDER BY received_at DESC, seq DESC LIMIT :n"
            ),
            {"p": project_id, "g": group_id, "n": limit, "since": since},
        )
    )


def window_counts(db: Session, group_id: uuid.UUID, now: datetime) -> tuple[int, list[int]]:
    """(count in the current UTC hour, counts of the previous 24 hourly buckets that exist).
    Hour boundaries are computed here in UTC, never by the database session's time zone."""
    start = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    cur = db.execute(
        text(
            "SELECT coalesce(sum(count), 0) AS n FROM public.event_buckets "
            "WHERE group_id = :g AND bucket_start = :s"
        ),
        {"g": group_id, "s": start},
    ).one()
    prev = db.execute(
        text(
            "SELECT count AS cnt FROM public.event_buckets WHERE group_id = :g "
            "AND bucket_start < :s AND bucket_start >= :f ORDER BY bucket_start"
        ),
        {"g": group_id, "s": start, "f": start - timedelta(hours=24)},
    ).all()
    return int(cur.n), [int(r.cnt) for r in prev]


# ---- correlation lookups (project scoped) --------------------------------------------------


def run_exists(db: Session, project_id: uuid.UUID, run_id: uuid.UUID) -> bool:
    return (
        db.execute(
            text("SELECT 1 FROM public.test_runs WHERE id = :i AND project_id = :p"),
            {"i": run_id, "p": project_id},
        ).first()
        is not None
    )


def result_exists(db: Session, project_id: uuid.UUID, result_id: uuid.UUID) -> bool:
    return (
        db.execute(
            text(
                "SELECT 1 FROM public.test_results r JOIN public.test_runs tr ON tr.id = r.run_id "
                "WHERE r.id = :i AND tr.project_id = :p"
            ),
            {"i": result_id, "p": project_id},
        ).first()
        is not None
    )


def finding_exists(db: Session, project_id: uuid.UUID, finding_id: uuid.UUID) -> bool:
    return (
        db.execute(
            text("SELECT 1 FROM public.findings WHERE id = :i AND project_id = :p"),
            {"i": finding_id, "p": project_id},
        ).first()
        is not None
    )


def active_run_at(db: Session, project_id: uuid.UUID, at: datetime) -> uuid.UUID | None:
    """A run of the project whose start-to-finish window contains ``at`` (proximity only)."""
    row = db.execute(
        text(
            "SELECT id FROM public.test_runs WHERE project_id = :p AND started_at IS NOT NULL "
            "AND started_at <= :at AND (finished_at IS NULL OR finished_at >= :at) "
            "ORDER BY started_at DESC LIMIT 1"
        ),
        {"p": project_id, "at": at},
    ).first()
    return row.id if row else None


# ---- event de-duplication ---------------------------------------------------------------------


def claim_event_id(db: Session, project_id: uuid.UUID, event_id: uuid.UUID) -> bool:
    """True when this event id has not been accepted in the last 24 hours (and records it);
    False for a retry of an event already accepted. An id older than 24 hours is reusable."""
    row = db.execute(
        text(
            "INSERT INTO public.ingest_event_ids (project_id, event_id) VALUES (:p, :e) "
            "ON CONFLICT (project_id, event_id) DO UPDATE SET received_at = now() "
            "WHERE public.ingest_event_ids.received_at < now() - interval '24 hours' "
            "RETURNING 1"
        ),
        {"p": project_id, "e": event_id},
    ).first()
    return row is not None


# ---- traces ---------------------------------------------------------------------------------------


def runs_by_trace(db: Session, project_id: uuid.UUID, trace_id: str) -> list[Row]:
    return _rows(
        db.execute(
            text(
                "SELECT id, status, plan_id, started_at, finished_at, created_at, trace_id "
                "FROM public.test_runs WHERE project_id = :p AND trace_id = :t"
            ),
            {"p": project_id, "t": trace_id},
        )
    )


def agent_runs_by_trace(db: Session, project_id: uuid.UUID, trace_id: str) -> list[Row]:
    return _rows(
        db.execute(
            text(
                "SELECT id, workflow, status, started_at, finished_at, trace_id "
                "FROM public.agent_runs WHERE project_id = :p AND trace_id = :t"
            ),
            {"p": project_id, "t": trace_id},
        )
    )


def samples_by_trace(
    db: Session, project_id: uuid.UUID, trace_id: str, limit: int, since: datetime
) -> list[Row]:
    return _rows(
        db.execute(
            text(
                f"SELECT {_SAMPLE_COLS} FROM public.events WHERE project_id = :p "
                "AND trace_id = :t AND received_at >= :since "
                "ORDER BY received_at, seq LIMIT :n"
            ),
            {"p": project_id, "t": trace_id, "since": since, "n": limit},
        )
    )


# ---- model usage and resource figures (estimates; nothing here is a measured bill) -------------


def usage_totals(db: Session, project_id: uuid.UUID, since: datetime) -> Row:
    row = db.execute(
        text(
            "SELECT count(*) AS calls, "
            "count(*) FILTER (WHERE outcome = 'ok') AS ok, "
            "count(*) FILTER (WHERE outcome = 'blocked_by_budget' OR blocked_by_budget) AS blocked, "
            "count(*) FILTER (WHERE outcome NOT IN ('ok', 'blocked_by_budget', 'reserved')) AS failed, "
            "count(*) FILTER (WHERE outcome = 'reserved') AS unsettled, "
            "count(*) FILTER (WHERE latency_ms IS NULL AND outcome = 'ok') AS no_latency, "
            "coalesce(sum(input_tokens), 0) AS input_tokens, "
            "coalesce(sum(output_tokens), 0) AS output_tokens, "
            "coalesce(sum(estimated_cost_usd), 0) AS cost, "
            "coalesce(sum(GREATEST(attempts - 1, 0)), 0) AS retries, "
            "coalesce(avg(latency_ms), 0) AS avg_latency_ms, "
            "coalesce(max(latency_ms), 0) AS max_latency_ms "
            "FROM public.llm_usage WHERE project_id = :p AND created_at >= :s"
        ),
        {"p": project_id, "s": since},
    ).one()
    return dict(row._mapping)


def daily_cost(db: Session, project_id: uuid.UUID, since: datetime, until: datetime) -> list[float]:
    """Estimated cost per UTC day with any usage in [since, until)."""
    rows = db.execute(
        text(
            "SELECT sum(estimated_cost_usd) AS c FROM public.llm_usage WHERE project_id = :p "
            "AND created_at >= :s AND created_at < :u GROUP BY (created_at AT TIME ZONE 'UTC')::date"
        ),
        {"p": project_id, "s": since, "u": until},
    ).all()
    return [float(r.c) for r in rows]


def agent_run_counts(db: Session, project_id: uuid.UUID, since: datetime) -> Row:
    row = db.execute(
        text(
            "SELECT count(*) AS runs, "
            "coalesce(max(calls), 0) AS max_calls_one_run FROM ("
            "SELECT ar.id, (SELECT coalesce(sum(u.attempts), 0) FROM public.llm_usage u "
            "WHERE u.agent_run_id = ar.id) AS calls FROM public.agent_runs ar "
            "WHERE ar.project_id = :p AND ar.started_at >= :s) t"
        ),
        {"p": project_id, "s": since},
    ).one()
    return dict(row._mapping)


def agent_step_counts(db: Session, project_id: uuid.UUID, since: datetime) -> Row:
    row = db.execute(
        text(
            "SELECT count(*) AS steps, count(*) FILTER (WHERE s.kind = 'llm') AS model_steps "
            "FROM public.agent_steps s JOIN public.agent_runs ar ON ar.id = s.agent_run_id "
            "WHERE ar.project_id = :p AND s.created_at >= :s"
        ),
        {"p": project_id, "s": since},
    ).one()
    return dict(row._mapping)


def run_duration_seconds(db: Session, run_id: uuid.UUID) -> tuple[uuid.UUID, float | None] | None:
    """(plan id, seconds from start to finish) of a finished run, else None."""
    row = db.execute(
        text(
            "SELECT plan_id, EXTRACT(EPOCH FROM (finished_at - started_at)) AS secs "
            "FROM public.test_runs WHERE id = :r AND started_at IS NOT NULL "
            "AND finished_at IS NOT NULL"
        ),
        {"r": run_id},
    ).first()
    return (row.plan_id, float(row.secs) if row.secs is not None else None) if row else None


def previous_run_durations(
    db: Session, plan_id: uuid.UUID, run_id: uuid.UUID, limit: int
) -> list[float]:
    """Durations of earlier completed runs of the same plan (the baseline)."""
    rows = db.execute(
        text(
            "SELECT EXTRACT(EPOCH FROM (finished_at - started_at)) AS secs FROM public.test_runs "
            "WHERE plan_id = :pl AND id <> :r AND status = 'completed' AND started_at IS NOT NULL "
            "AND finished_at IS NOT NULL AND finished_at < (SELECT finished_at FROM public.test_runs "
            "WHERE id = :r) ORDER BY finished_at DESC LIMIT :n"
        ),
        {"pl": plan_id, "r": run_id, "n": limit},
    ).all()
    return [float(r.secs) for r in rows]


# ---- stats ----------------------------------------------------------------------------------


def add_stats(
    db: Session, project_id: uuid.UUID, day: date, *, accepted: int, dropped: dict[str, int],
    eval_errors: int = 0,
) -> None:  # fmt: skip
    db.execute(
        text(
            "INSERT INTO public.ingest_stats (project_id, day, accepted, dropped, eval_errors) "
            "VALUES (:p, :d, :a, CAST(:dr AS jsonb), :e) ON CONFLICT (project_id, day) DO UPDATE SET "
            "accepted = public.ingest_stats.accepted + EXCLUDED.accepted, "
            "eval_errors = public.ingest_stats.eval_errors + EXCLUDED.eval_errors, "
            "dropped = (SELECT coalesce(jsonb_object_agg(k, "
            "coalesce((public.ingest_stats.dropped ->> k)::int, 0) + "
            "coalesce((EXCLUDED.dropped ->> k)::int, 0)), '{}'::jsonb) FROM ("
            "SELECT jsonb_object_keys(public.ingest_stats.dropped) AS k "
            "UNION SELECT jsonb_object_keys(EXCLUDED.dropped)) ks)"
        ),
        {"p": project_id, "d": day, "a": accepted, "dr": json.dumps(dropped), "e": eval_errors},
    )


def accepted_on(db: Session, project_id: uuid.UUID, day: date) -> int:
    row = db.execute(
        text("SELECT accepted FROM public.ingest_stats WHERE project_id = :p AND day = :d"),
        {"p": project_id, "d": day},
    ).first()
    return int(row.accepted) if row else 0


def stats_since(db: Session, project_id: uuid.UUID, since_day: date) -> list[Row]:
    return _rows(
        db.execute(
            text(
                "SELECT day, accepted, dropped, eval_errors FROM public.ingest_stats "
                "WHERE project_id = :p AND day >= :d ORDER BY day"
            ),
            {"p": project_id, "d": since_day},
        )
    )


def last_event_time(db: Session, project_id: uuid.UUID) -> datetime | None:
    row = db.execute(
        text("SELECT max(last_seen) AS latest FROM public.event_groups WHERE project_id = :p"),
        {"p": project_id},
    ).one()
    return row.latest  # type: ignore[no-any-return]


def telemetry_counts(db: Session, project_id: uuid.UUID, since: datetime) -> Row:
    """Facts about what was received, for the telemetry disclosure (samples, not totals)."""
    levels = db.execute(
        text(
            "SELECT level_class, coalesce(sum(total_count), 0) AS n FROM public.event_groups "
            "WHERE project_id = :p AND last_seen >= :s GROUP BY level_class"
        ),
        {"p": project_id, "s": since},
    ).all()
    envs = db.execute(
        text(
            "SELECT environment, coalesce(sum(total_count), 0) AS n FROM public.event_groups "
            "WHERE project_id = :p AND last_seen >= :s GROUP BY environment"
        ),
        {"p": project_id, "s": since},
    ).all()
    groups = db.execute(
        text(
            "SELECT count(*) AS total, count(*) FILTER (WHERE has_stack) AS with_stack "
            "FROM public.event_groups WHERE project_id = :p"
        ),
        {"p": project_id},
    ).one()
    samples = db.execute(
        text(
            "SELECT count(*) AS total, count(*) FILTER (WHERE trace_id IS NOT NULL) AS with_trace, "
            "count(*) FILTER (WHERE (correlation ->> 'run_id') IS NOT NULL "
            "OR (correlation ->> 'result_id') IS NOT NULL "
            "OR (correlation ->> 'finding_id') IS NOT NULL "
            "OR (correlation ->> 'trace_run_id') IS NOT NULL "
            "OR (correlation ->> 'trace_agent_run_id') IS NOT NULL) AS linked FROM public.events "
            "WHERE project_id = :p"
        ),
        {"p": project_id},
    ).one()
    return {
        "levels": {r.level_class: int(r.n) for r in levels},
        "environments": {r.environment: int(r.n) for r in envs},
        "groups": int(groups.total),
        "groups_with_stack": int(groups.with_stack),
        "samples": int(samples.total),
        "samples_with_trace_id": int(samples.with_trace),
        "samples_with_verified_link": int(samples.linked),
    }


# ---- alerts ----------------------------------------------------------------------------------


def open_alert_count(db: Session, project_id: uuid.UUID) -> int:
    row = db.execute(
        text(
            "SELECT count(*) AS n FROM public.alerts WHERE project_id = :p AND status <> 'resolved'"
        ),
        {"p": project_id},
    ).one()
    return int(row.n)


def upsert_alert(
    db: Session, *, project_id: uuid.UUID, rule: str, rule_version: str, subject_key: str,
    group_id: uuid.UUID | None, run_id: uuid.UUID | None, result_id: uuid.UUID | None,
    finding_id: uuid.UUID | None, severity: str, title: str, measured: dict[str, Any],
    evidence: dict[str, Any], next_action: str, now: datetime,
) -> tuple[uuid.UUID, bool]:  # fmt: skip
    """Create the open alert for (project, rule, subject) or count another occurrence on it.
    Returns (id, created)."""
    row = db.execute(
        text(
            "INSERT INTO public.alerts (project_id, rule, rule_version, subject_key, group_id, "
            "run_id, result_id, finding_id, severity, title, measured, evidence, next_action, "
            "first_seen, last_seen) VALUES (:p, :r, :rv, :sk, :g, :ru, :re, :f, :sev, :t, "
            "CAST(:m AS jsonb), CAST(:ev AS jsonb), :na, :now, :now) "
            "ON CONFLICT (project_id, rule, subject_key) WHERE status <> 'resolved' DO UPDATE SET "
            "occurrences = public.alerts.occurrences + 1, last_seen = EXCLUDED.last_seen, "
            "measured = EXCLUDED.measured, evidence = EXCLUDED.evidence "
            "RETURNING id, (xmax = 0) AS created"
        ),
        {"p": project_id, "r": rule, "rv": rule_version, "sk": subject_key, "g": group_id,
         "ru": run_id, "re": result_id, "f": finding_id, "sev": severity, "t": title,
         "m": json.dumps(measured), "ev": json.dumps(evidence), "na": next_action, "now": now},
    ).one()  # fmt: skip
    return row.id, bool(row.created)


def add_history(
    db: Session, *, alert_id: uuid.UUID, project_id: uuid.UUID, action: str,
    actor_user_id: uuid.UUID | None, note: str | None = None, detail: dict[str, Any] | None = None,
) -> None:  # fmt: skip
    db.execute(
        text(
            "INSERT INTO public.alert_history (alert_id, project_id, action, actor_user_id, note, "
            "detail) VALUES (:a, :p, :ac, :u, :n, CAST(:d AS jsonb))"
        ),
        {"a": alert_id, "p": project_id, "ac": action, "u": actor_user_id, "n": note,
         "d": json.dumps(detail or {})},
    )  # fmt: skip


def get_alert(db: Session, project_id: uuid.UUID, alert_id: uuid.UUID) -> Row | None:
    return _one(
        db.execute(
            text(f"SELECT {_ALERT_COLS} FROM public.alerts WHERE id = :i AND project_id = :p"),
            {"i": alert_id, "p": project_id},
        )
    )


def list_alerts(
    db: Session, project_id: uuid.UUID, *, status: str | None, severity: str | None,
    rule: str | None, limit: int, offset: int,
) -> list[Row]:  # fmt: skip
    return _rows(
        db.execute(
            text(
                f"SELECT {_ALERT_COLS} FROM public.alerts WHERE project_id = :p "
                "AND (CAST(:s AS text) IS NULL OR status = :s) "
                "AND (CAST(:sev AS text) IS NULL OR severity = :sev) "
                "AND (CAST(:r AS text) IS NULL OR rule = :r) "
                "ORDER BY (status = 'resolved'), last_seen DESC, id LIMIT :n OFFSET :o"
            ),
            {"p": project_id, "s": status, "sev": severity, "r": rule, "n": limit, "o": offset},
        )
    )


def list_history(db: Session, alert_id: uuid.UUID) -> list[Row]:
    return _rows(
        db.execute(
            text(
                "SELECT id, action, actor_user_id, note, detail, created_at "
                "FROM public.alert_history WHERE alert_id = :a ORDER BY id"
            ),
            {"a": alert_id},
        )
    )


def transition_alert(
    db: Session,
    project_id: uuid.UUID,
    alert_id: uuid.UUID,
    *,
    to: str,
    from_statuses: tuple[str, ...],
) -> bool:
    """Conditional on the current status, so two people cannot both succeed."""
    closed = "now()" if to == "resolved" else "NULL"
    res = db.execute(
        text(
            f"UPDATE public.alerts SET status = :to, closed_at = {closed} "
            "WHERE id = :i AND project_id = :p AND status = ANY(:fr)"
        ),
        {"to": to, "i": alert_id, "p": project_id, "fr": list(from_statuses)},
    )
    return bool(res.rowcount)  # type: ignore[attr-defined]


def reopen_for_group(db: Session, project_id: uuid.UUID, group_id: uuid.UUID) -> Row | None:
    """Reopen the most recently resolved new-error alert of a group (a recurrence)."""
    return _one(
        db.execute(
            text(
                "UPDATE public.alerts SET status = 'open', closed_at = NULL, "
                "occurrences = occurrences + 1, last_seen = now() WHERE id = ("
                "SELECT id FROM public.alerts WHERE project_id = :p AND group_id = :g "
                "AND rule = 'new_error_group' AND status = 'resolved' "
                "AND NOT EXISTS (SELECT 1 FROM public.alerts o WHERE o.project_id = :p "
                "AND o.group_id = :g AND o.rule = 'new_error_group' AND o.status <> 'resolved') "
                "ORDER BY closed_at DESC LIMIT 1) "
                f"RETURNING {_ALERT_COLS}"
            ),
            {"p": project_id, "g": group_id},
        )
    )


def set_investigation(
    db: Session, project_id: uuid.UUID, alert_id: uuid.UUID, run_id: uuid.UUID
) -> None:
    db.execute(
        text(
            "UPDATE public.alerts SET agent_run_id = :r, cause_status = 'investigated' "
            "WHERE id = :i AND project_id = :p"
        ),
        {"r": run_id, "i": alert_id, "p": project_id},
    )


def proposals_for_alert(db: Session, project_id: uuid.UUID, alert_id: uuid.UUID) -> list[uuid.UUID]:
    rows = db.execute(
        text(
            "SELECT id FROM public.regression_tests WHERE project_id = :p AND alert_id = :a "
            "ORDER BY created_at DESC"
        ),
        {"p": project_id, "a": alert_id},
    ).all()
    return [r.id for r in rows]


def failed_results_of_run(db: Session, run_id: uuid.UUID, limit: int) -> list[Row]:
    return _rows(
        db.execute(
            text(
                "SELECT r.id, r.status FROM public.test_results r WHERE r.run_id = :r "
                "AND r.status IN ('failed', 'error', 'timed_out') ORDER BY r.created_at, r.id LIMIT :n"
            ),
            {"r": run_id, "n": limit},
        )
    )


def project_lock(db: Session, project_id: uuid.UUID) -> None:
    """Serialise rule evaluation per project for the rest of this transaction."""
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"alerts:{project_id}"},
    )


def projects_for_scheduled_rules(db: Session, limit: int = 5000) -> list[uuid.UUID]:
    """Active projects whose time-driven rules should be evaluated: ingestion is on, or the
    project used the model or ran an assistant workflow in the last 48 hours."""
    rows = db.execute(
        text(
            "SELECT p.id FROM public.projects p WHERE p.archived_at IS NULL AND ("
            "EXISTS (SELECT 1 FROM public.policies po WHERE po.scope = 'project' "
            "AND po.project_id = p.id AND po.key = 'observability_ingest' "
            "AND (po.value ->> 'enabled') = 'true') "
            "OR EXISTS (SELECT 1 FROM public.llm_usage u WHERE u.project_id = p.id "
            "AND u.created_at >= now() - interval '48 hours') "
            "OR EXISTS (SELECT 1 FROM public.agent_runs a WHERE a.project_id = p.id "
            "AND a.started_at >= now() - interval '48 hours')) ORDER BY p.id LIMIT :n"
        ),
        {"n": limit},
    ).all()
    return [r.id for r in rows]


# ---- retention -------------------------------------------------------------------------------


def purge(
    db: Session, *, sample_before: datetime, group_before: datetime, key_before: datetime,
    stats_before: date, dry_run: bool,
) -> dict[str, int]:  # fmt: skip
    """Delete expired rows; returns counts (and deletes nothing when ``dry_run``). Alerts and
    groups a regression proposal points to are kept, as are open alerts and their groups."""
    out: dict[str, int] = {}
    steps: tuple[tuple[str, str, dict[str, Any]], ...] = (
        ("events", "FROM public.events WHERE received_at < :sb", {"sb": sample_before}),
        (
            "event_buckets",
            "FROM public.event_buckets WHERE bucket_start < :sb",
            {"sb": sample_before},
        ),
        (
            "alerts",
            "FROM public.alerts a WHERE a.status = 'resolved' AND a.closed_at < :gb "
            "AND NOT EXISTS (SELECT 1 FROM public.regression_tests t WHERE t.alert_id = a.id)",
            {"gb": group_before},
        ),
        (
            "event_groups",
            "FROM public.event_groups g WHERE g.last_seen < :gb "
            "AND NOT EXISTS (SELECT 1 FROM public.regression_tests t WHERE t.event_group_id = g.id) "
            "AND NOT EXISTS (SELECT 1 FROM public.alerts a WHERE a.group_id = g.id)",
            {"gb": group_before},
        ),
        (
            "ingest_keys",
            "FROM public.ingest_keys WHERE (revoked_at IS NOT NULL AND revoked_at < :kb) "
            "OR expires_at < :kb",
            {"kb": key_before},
        ),
        ("ingest_stats", "FROM public.ingest_stats WHERE day < :sd", {"sd": stats_before}),
        (
            "ingest_event_ids",
            "FROM public.ingest_event_ids WHERE received_at < now() - interval '2 days'",
            {},
        ),
    )
    for name, clause, params in steps:
        if dry_run:
            row = db.execute(text(f"SELECT count(*) AS n {clause}"), params).one()
            out[name] = int(row.n)
        else:
            res = db.execute(text(f"DELETE {clause}"), params)
            out[name] = int(res.rowcount)  # type: ignore[attr-defined]
    return out
