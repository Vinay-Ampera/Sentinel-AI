"""Ingest keys and event ingestion (Stage 12, ADR-0011).

A key is one project's write-only credential: ``sai_ing_<key_id>_<secret>`` with a 32-byte
random secret shown once; only a keyed hash is stored. Ingestion validates each event against the
strict schema, drops what is below the level floor or over a cap (counting every drop by reason),
redacts before anything is stored, verifies correlation claims against the project, groups events
by a deterministic fingerprint, keeps hourly counts and a few samples, and then runs the event
alert rules for the touched groups. External events are the application's own claims: nothing here
changes a finding, a run or a verification state, and no model is called."""

import secrets
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from sentinel_ai.core import security
from sentinel_ai.core.config import Settings
from sentinel_ai.core.errors import DomainError
from sentinel_ai.repositories import observability as repo
from sentinel_ai.repositories.identity import UserRecord
from sentinel_ai.schemas.observability import EventIn
from sentinel_ai.services import alerts, audit
from sentinel_ai.services import event_fingerprint as fp
from sentinel_ai.services.audit import RequestContext
from sentinel_ai.services.event_redaction import EventRedactor

KEY_PREFIX = "sai_ing_"
KEY_PURPOSE = "ingest-key"
LEVEL_FLOOR = ("warning", "error", "fatal")
FIRST_SAMPLES_KEPT = 5
TIMESTAMP_PAST = timedelta(hours=24)
TIMESTAMP_FUTURE = timedelta(minutes=5)
DROP_REASONS = (
    "invalid_schema", "level_below_threshold", "duplicate", "quota", "rate_limited", "group_cap",
    "too_large",
)  # fmt: skip


@dataclass(frozen=True)
class KeyAuth:
    key_row_id: uuid.UUID
    project_id: uuid.UUID


@dataclass
class IngestResult:
    accepted: int = 0
    dropped: Counter[str] = field(default_factory=Counter)


def now_utc() -> datetime:
    return datetime.now(UTC)


# ---- keys ----------------------------------------------------------------------------------


def _hash(settings: Settings, raw: str) -> bytes:
    return security.keyed_hash(settings.pepper(), KEY_PURPOSE, raw)


def _split(raw: str) -> str | None:
    """The 12-hex key id of a well-formed key, else None."""
    if not raw.startswith(KEY_PREFIX) or len(raw) < len(KEY_PREFIX) + 14 or len(raw) > 200:
        return None
    key_id = raw[len(KEY_PREFIX) : len(KEY_PREFIX) + 12]
    if raw[len(KEY_PREFIX) + 12] != "_" or any(c not in "0123456789abcdef" for c in key_id):
        return None
    return key_id


def authenticate(db: Session, settings: Settings, raw: str | None) -> KeyAuth | None:
    """Unknown, malformed, expired, revoked and archived-project keys all look the same."""
    key_id = _split(raw) if raw else None
    row = repo.get_key_for_auth(db, key_id) if key_id else None
    # Always hash and compare, so a missing key id costs the same as a wrong secret.
    supplied = _hash(settings, raw or "")
    stored = row["key_hash"] if row else b"\x00" * 32
    matches = security.constant_time_equal(bytes(stored), supplied)
    if row is None or not matches:
        return None
    if row["revoked_at"] is not None or row["expires_at"] <= now_utc():
        return None
    if row["archived_at"] is not None:
        return None
    repo.touch_key(db, row["id"])
    return KeyAuth(row["id"], row["project_id"])


def _key_status(row: dict[str, Any]) -> str:
    if row["revoked_at"] is not None:
        return "revoked"
    return "expired" if row["expires_at"] <= now_utc() else "active"


def key_view(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "status": _key_status(row)}


def create_key(
    db: Session, ctx: RequestContext, settings: Settings, user: UserRecord,
    project_id: uuid.UUID, *, label: str, expires_in_days: int | None,
) -> tuple[dict[str, Any], str]:  # fmt: skip
    """Callers have checked ``manage`` access. Returns the key row and the raw key (once)."""
    days = expires_in_days or settings.ingest_key_default_days
    if days > settings.ingest_key_max_days:
        raise DomainError(
            422, "validation_failed", f"Keys last at most {settings.ingest_key_max_days} days"
        )
    clean = " ".join(label.split())
    if not clean:
        raise DomainError(422, "validation_failed", "label must not be blank")
    if repo.count_active_keys(db, project_id) >= settings.ingest_keys_per_project:
        raise DomainError(
            409, "key_limit", f"At most {settings.ingest_keys_per_project} active keys per project"
        )
    key_id = secrets.token_hex(6)
    raw = f"{KEY_PREFIX}{key_id}_{secrets.token_urlsafe(32)}"
    row = repo.insert_key(
        db, project_id=project_id, key_id=key_id, key_hash=_hash(settings, raw),
        label=clean[:80], created_by=user.id, expires_at=now_utc() + timedelta(days=days),
    )  # fmt: skip
    audit.record(
        db, ctx, action="ingest_key.create", outcome="success", actor_user_id=user.id,
        project_id=project_id, target_type="ingest_key", target_id=str(row["id"]),
        detail={"label": clean[:80], "expires_in_days": days},
    )  # fmt: skip
    return key_view(row), raw


def list_keys(db: Session, project_id: uuid.UUID) -> list[dict[str, Any]]:
    return [key_view(r) for r in repo.list_keys(db, project_id)]


def revoke_key(
    db: Session, ctx: RequestContext, user: UserRecord, project_id: uuid.UUID, key_row_id: uuid.UUID
) -> dict[str, Any]:
    if repo.get_key(db, project_id, key_row_id) is None:
        raise DomainError(404, "not_found", "Ingest key not found")
    row = repo.revoke_key(db, project_id, key_row_id)
    if row is None:
        raise DomainError(409, "already_revoked", "This key is already revoked")
    audit.record(
        db, ctx, action="ingest_key.revoke", outcome="success", actor_user_id=user.id,
        project_id=project_id, target_type="ingest_key", target_id=str(key_row_id), detail={},
    )  # fmt: skip
    return key_view(row)


# ---- ingestion -----------------------------------------------------------------------------


def _bucket(now: datetime) -> datetime:
    return now.replace(minute=0, second=0, microsecond=0)


def _timestamp(event: EventIn, now: datetime) -> tuple[datetime | None, bool]:
    """(client timestamp kept for display, untrusted?). Rules always use ``received_at``."""
    if event.timestamp is None:
        return None, False
    ts = event.timestamp if event.timestamp.tzinfo else event.timestamp.replace(tzinfo=UTC)
    if ts < now - TIMESTAMP_PAST or ts > now + TIMESTAMP_FUTURE:
        return None, True
    return ts, False


def _correlate(
    db: Session, project_id: uuid.UUID, event: EventIn, now: datetime, during: dict[str, Any]
) -> tuple[dict[str, str], dict[str, Any]]:
    """(claimed ids, verified correlation). A claim is a link only if the record belongs to this
    project; otherwise it is listed as unverified and never rendered as a link."""
    claimed: dict[str, str] = {}
    verified: dict[str, Any] = {}
    unverified: list[str] = []
    checks = (
        ("run_id", event.run_id, repo.run_exists),
        ("result_id", event.result_id, repo.result_exists),
        ("finding_id", event.finding_id, repo.finding_exists),
    )
    for name, value, exists in checks:
        if value is None:
            continue
        claimed[name] = str(value)
        if exists(db, project_id, value):
            verified[name] = str(value)
        else:
            unverified.append(name)
    if unverified:
        verified["unverified"] = unverified
    if event.trace_id:
        # The same W3C trace id as a platform workflow (a run or an assistant run of this
        # project): correlated by identifier, so it counts as verified, unlike time overlap.
        run = next(iter(repo.runs_by_trace(db, project_id, event.trace_id)), None)
        agent = next(iter(repo.agent_runs_by_trace(db, project_id, event.trace_id)), None)
        if run is not None:
            verified["trace_run_id"] = str(run["id"])
        if agent is not None:
            verified["trace_agent_run_id"] = str(agent["id"])
    if (
        event.environment in ("local", "development", "staging")
        and "run_id" not in verified
        and "trace_run_id" not in verified
    ):
        if "run" not in during:  # one lookup per batch: every event shares ``now``
            active = repo.active_run_at(db, project_id, now)
            during["run"] = str(active) if active else None
        if during["run"]:
            verified["during_run"] = during["run"]
    return claimed, verified


def _prepare(
    redactor: EventRedactor, event: EventIn, timestamp: datetime | None, untrusted: bool
) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    message = redactor.text(event.message, counts)[:2048]
    error_type = redactor.text(event.error_type, counts)[:128] if event.error_type else None
    stack = redactor.text(event.stack, counts)[:8192] if event.stack else None
    release = redactor.text(event.release, counts)[:64] if event.release else None
    return {
        "event_id": event.event_id, "client_timestamp": timestamp, "timestamp_untrusted": untrusted,
        "level": event.level, "service": event.service, "environment": event.environment,
        "message": message, "error_type": error_type, "stack": stack, "release": release,
        "attributes": redactor.attributes(event.attributes, counts), "trace_id": event.trace_id,
        "span_id": event.span_id, "redactions": dict(counts),
    }  # fmt: skip


def ingest_batch(
    db: Session, settings: Settings, redactor: EventRedactor, auth: KeyAuth,
    raw_events: list[Any], *, now: datetime | None = None,
) -> IngestResult:  # fmt: skip
    """Store a batch in the caller's transaction. Never raises for one bad event."""
    now = now or now_utc()
    project_id = auth.project_id
    result = IngestResult()
    _, thresholds = alerts.policy_thresholds(db, project_id)
    repo.project_lock(db, project_id)  # one writer per project: counts and caps stay exact
    remaining = max(0, settings.event_daily_quota - repo.accepted_on(db, project_id, now.date()))
    group_total = repo.count_groups(db, project_id)
    during: dict[str, Any] = {}
    touched: dict[uuid.UUID, dict[str, Any]] = {}
    for raw in raw_events:
        try:
            event = EventIn.model_validate(raw)
        except ValidationError:
            result.dropped["invalid_schema"] += 1
            continue
        if event.level not in LEVEL_FLOOR:
            result.dropped["level_below_threshold"] += 1
            continue
        if event.event_id is not None and not repo.claim_event_id(db, project_id, event.event_id):
            result.dropped["duplicate"] += 1  # a retry of an event already accepted
            continue
        if result.accepted >= remaining:
            result.dropped["quota"] += 1
            continue
        ts, untrusted = _timestamp(event, now)
        data = _prepare(redactor, event, ts, untrusted)
        claimed, correlation = _correlate(db, project_id, event, now, during)
        digest, norm = fp.fingerprint(
            project_id, service=data["service"], environment=data["environment"],
            level_class=fp.level_class(data["level"]), error_type=data["error_type"],
            message=data["message"], stack=data["stack"],
        )  # fmt: skip
        overflow = False
        if group_total >= settings.event_max_groups_per_project and not repo.group_exists(
            db, project_id, digest
        ):
            digest, norm, overflow = fp.overflow_fingerprint(project_id), "", True
            result.dropped["group_cap"] += 1
        group = repo.upsert_group(
            db, project_id=project_id, fingerprint=digest, fp_version=fp.VERSION,
            service="_overflow" if overflow else data["service"],
            environment="unknown" if overflow else data["environment"],
            level_class="error" if overflow else fp.level_class(data["level"]),
            error_type=None if overflow else data["error_type"],
            message_norm=norm or "Groups beyond the per-project limit",
            has_stack=bool(data["stack"]), is_overflow=overflow, now=now,
        )  # fmt: skip
        if group["inserted"]:
            group_total += 1
        repo.bump_bucket(db, group["id"], _bucket(now))
        repo.insert_sample(
            db, project_id=project_id, group_id=group["id"], key_row_id=auth.key_row_id,
            received_at=now, e={**data, "claimed": claimed, "correlation": correlation},
        )  # fmt: skip
        if group["total_count"] > settings.event_samples_per_group:
            repo.trim_samples(db, group["id"], FIRST_SAMPLES_KEPT, settings.event_samples_per_group)
        result.accepted += 1
        touched[group["id"]] = group

    eval_errors = 0
    try:
        with db.begin_nested():
            alerts.evaluate_groups(
                db, project_id, list(touched.values()), now, thresholds, settings
            )
            if result.accepted:
                alerts.close_gap_alert(db, project_id)
            if result.dropped["quota"] or result.dropped["group_cap"]:
                alerts.raise_ingest_dropping(db, project_id, result.dropped, now, settings)
    except Exception:  # a rule failure must never lose accepted events
        eval_errors = 1
    repo.add_stats(
        db, project_id, now.date(), accepted=result.accepted, dropped=dict(result.dropped),
        eval_errors=eval_errors,
    )  # fmt: skip
    return result


def record_drop(
    db: Session, project_id: uuid.UUID, reason: str, count: int, now: datetime | None = None
) -> None:
    """Count events that were refused before the batch was processed (rate limit, size)."""
    repo.add_stats(db, project_id, (now or now_utc()).date(), accepted=0, dropped={reason: count})
