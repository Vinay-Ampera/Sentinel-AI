"""Policy for observability (ADR-0011): whether ingestion is on, and alert thresholds.

Two project-level keys edited by project managers (`observability_ingest`, `alert_thresholds`)
and one organization-level key (`alert_threshold_bounds`, Super Admin) that can only *narrow*
the built-in limits. Ingestion is **off** unless a manager turned it on. A project threshold
must lie inside the effective bounds when it is set, and a stored value that later falls outside
narrowed bounds is clamped when read. Missing or malformed stored values fall back to the
defaults, as in ``policy.py``."""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from sentinel_ai.core.errors import DomainError
from sentinel_ai.repositories import policies

INGEST_KEY = "observability_ingest"
THRESHOLDS_KEY = "alert_thresholds"
BOUNDS_KEY = "alert_threshold_bounds"

# name -> (default, minimum, maximum): the built-in limits nobody can widen.
BOUNDS: dict[str, tuple[float, float, float]] = {
    "new_group_events": (3, 1, 100),  # events of a new error group inside the window
    "new_group_window_minutes": (15, 5, 240),
    "spike_min_events": (5, 2, 10_000),  # events in the current hour
    "spike_ratio": (3.0, 1.5, 20.0),  # times the median of the previous 24 hourly buckets
    "gap_silence_hours": (6, 1, 168),
    "cost_spike_ratio": (3.0, 1.5, 20.0),  # estimated model cost vs the median of prior days
    "cost_spike_min_usd": (0.5, 0.01, 1000.0),  # estimated cost in the last 24 hours
    "runaway_runs_per_hour": (20, 3, 1000),  # assistant workflow runs started in an hour
    "llm_error_rate_percent": (50, 10, 100),  # share of failed model calls in the last hour
    "run_duration_ratio": (3.0, 1.5, 20.0),  # run duration vs the median of earlier runs
}
DESCRIPTIONS: dict[str, str] = {
    "new_group_events": "Events a new error group needs before it raises an alert",
    "new_group_window_minutes": "Minutes after an error first appears in which it counts as new",
    "spike_min_events": "Events in the current hour before an error rate spike can be raised",
    "spike_ratio": "Times the median of the previous 24 hourly counts that counts as a spike",
    "gap_silence_hours": "Hours without any event, after activity, before a silence alert",
    "cost_spike_ratio": "Times the median daily estimated model cost that counts as a spike",
    "cost_spike_min_usd": "Estimated 24-hour model cost (USD) under which no cost alert is raised",
    "runaway_runs_per_hour": "Assistant workflow runs in one hour that count as running away",
    "llm_error_rate_percent": "Percent of failed model calls in an hour that raises an alert",
    "run_duration_ratio": "Times the median duration of earlier runs of a plan that counts as long",
}
DEFAULT_THRESHOLDS: dict[str, float] = {k: v[0] for k, v in BOUNDS.items()}
Bounds = dict[str, tuple[float, float]]


def _number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _fmt(v: float) -> str:
    return str(int(v)) if v == int(v) else str(v)


def builtin_limits() -> list[dict[str, Any]]:
    """What an organization may narrow: every threshold with its default and built-in range."""
    return [
        {"name": k, "default": v[0], "min": v[1], "max": v[2], "description": DESCRIPTIONS[k]}
        for k, v in BOUNDS.items()
    ]


def hard_bounds() -> Bounds:
    return {k: (v[1], v[2]) for k, v in BOUNDS.items()}


def validate_ingest(value: Any) -> dict[str, bool]:
    if (
        not isinstance(value, dict)
        or set(value) != {"enabled"}
        or not isinstance(value["enabled"], bool)
    ):
        raise DomainError(422, "validation_failed", 'Value must be {"enabled": true|false}')
    return {"enabled": value["enabled"]}


def validate_bounds(value: Any) -> dict[str, dict[str, float]]:
    """Organization bounds: ``{name: {"min": n, "max": n}}``, each inside the built-in limits
    (an organization can narrow a range, never widen it)."""
    bad = DomainError(
        422,
        "validation_failed",
        'Value must map known threshold names to {"min": n, "max": n} inside the built-in limits: '
        + ", ".join(f"{k} ({_fmt(v[1])}-{_fmt(v[2])})" for k, v in BOUNDS.items()),
    )
    if not isinstance(value, dict) or not value:
        raise bad
    out: dict[str, dict[str, float]] = {}
    for name, rng in value.items():
        if name not in BOUNDS or not isinstance(rng, dict) or set(rng) != {"min", "max"}:
            raise bad
        low, high = rng["min"], rng["max"]
        if not _number(low) or not _number(high) or low > high:
            raise bad
        _, hard_low, hard_high = BOUNDS[name]
        if low < hard_low or high > hard_high:
            raise bad
        out[name] = {"min": low, "max": high}
    return out


def effective_bounds(global_rows: dict[str, Any] | None) -> Bounds:
    """The built-in limits narrowed by the organization's valid stored bounds."""
    bounds = hard_bounds()
    stored = (global_rows or {}).get(BOUNDS_KEY)
    if isinstance(stored, dict):
        try:
            for name, rng in validate_bounds(stored).items():
                bounds[name] = (rng["min"], rng["max"])
        except DomainError:
            pass  # an invalid stored value is ignored in favour of the built-in limits
    return bounds


def validate_thresholds(value: Any, bounds: Bounds | None = None) -> dict[str, float]:
    ranges = bounds or hard_bounds()
    bad = DomainError(
        422,
        "validation_failed",
        "Value must map known threshold names to numbers inside the limits in force: "
        + ", ".join(f"{k} ({_fmt(r[0])}-{_fmt(r[1])})" for k, r in ranges.items()),
    )
    if not isinstance(value, dict) or not value:
        raise bad
    out: dict[str, float] = {}
    for name, number in value.items():
        if name not in ranges or not _number(number):
            raise bad
        low, high = ranges[name]
        if not low <= number <= high:
            raise bad
        out[name] = number
    return out


def thresholds(rows: dict[str, Any], global_rows: dict[str, Any] | None = None) -> dict[str, float]:
    """Defaults overlaid with the project's valid stored values, every value clamped into the
    limits in force (so narrowing the organization bounds takes effect on existing projects)."""
    ranges = effective_bounds(global_rows)
    merged = dict(DEFAULT_THRESHOLDS)
    stored = rows.get(THRESHOLDS_KEY)
    if isinstance(stored, dict):
        try:
            merged.update(validate_thresholds(stored, hard_bounds()))
        except DomainError:
            pass
    return {k: min(max(v, ranges[k][0]), ranges[k][1]) for k, v in merged.items()}


def ingest_enabled(rows: dict[str, Any]) -> bool:
    stored = rows.get(INGEST_KEY)
    return isinstance(stored, dict) and stored.get("enabled") is True


def load(db: Session, project_id: uuid.UUID) -> tuple[bool, dict[str, float]]:
    rows = policies.project_rows(db, project_id)
    return ingest_enabled(rows), thresholds(rows, policies.global_rows(db))
