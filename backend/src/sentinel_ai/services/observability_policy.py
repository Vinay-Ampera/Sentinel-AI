"""Project policy for observability (ADR-0011): whether ingestion is on, and alert thresholds.

Both are project-level policy keys edited through the normal policy route (project managers).
Ingestion is **off** unless a manager turned it on; threshold values are bounded constants so a
project can tune noise but cannot disable detection or set a nonsensical value. Missing or
malformed stored values fall back to the defaults, as in ``policy.py``."""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from sentinel_ai.core.errors import DomainError
from sentinel_ai.repositories import policies

INGEST_KEY = "observability_ingest"
THRESHOLDS_KEY = "alert_thresholds"

# name -> (default, minimum, maximum)
BOUNDS: dict[str, tuple[float, float, float]] = {
    "new_group_events": (3, 1, 100),  # events of a new error group inside the window
    "new_group_window_minutes": (15, 5, 240),
    "spike_min_events": (5, 2, 10_000),  # events in the current hour
    "spike_ratio": (3.0, 1.5, 20.0),  # times the median of the previous 24 hourly buckets
    "gap_silence_hours": (6, 1, 168),
}
DEFAULT_THRESHOLDS: dict[str, float] = {k: v[0] for k, v in BOUNDS.items()}


def validate_ingest(value: Any) -> dict[str, bool]:
    if (
        not isinstance(value, dict)
        or set(value) != {"enabled"}
        or not isinstance(value["enabled"], bool)
    ):
        raise DomainError(422, "validation_failed", 'Value must be {"enabled": true|false}')
    return {"enabled": value["enabled"]}


def validate_thresholds(value: Any) -> dict[str, float]:
    bad = DomainError(
        422,
        "validation_failed",
        "Value must map known threshold names to numbers inside their limits: "
        + ", ".join(
            f"{k} ({int(v[1]) if v[1] == int(v[1]) else v[1]}-{int(v[2])})"
            for k, v in BOUNDS.items()
        ),
    )
    if not isinstance(value, dict) or not value:
        raise bad
    out: dict[str, float] = {}
    for name, number in value.items():
        if name not in BOUNDS or isinstance(number, bool) or not isinstance(number, int | float):
            raise bad
        _, low, high = BOUNDS[name]
        if not low <= number <= high:
            raise bad
        out[name] = number
    return out


def thresholds(rows: dict[str, Any]) -> dict[str, float]:
    """Defaults overlaid with the project's valid stored values."""
    merged = dict(DEFAULT_THRESHOLDS)
    stored = rows.get(THRESHOLDS_KEY)
    if isinstance(stored, dict):
        try:
            merged.update(validate_thresholds(stored))
        except DomainError:
            pass
    return merged


def ingest_enabled(rows: dict[str, Any]) -> bool:
    stored = rows.get(INGEST_KEY)
    return isinstance(stored, dict) and stored.get("enabled") is True


def load(db: Session, project_id: uuid.UUID) -> tuple[bool, dict[str, float]]:
    rows = policies.project_rows(db, project_id)
    return ingest_enabled(rows), thresholds(rows)
