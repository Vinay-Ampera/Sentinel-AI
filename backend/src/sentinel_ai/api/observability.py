"""Event ingestion, ingest keys, event groups, alerts and telemetry status (Stage 12, ADR-0011).

Two kinds of caller. ``POST /ingest/events`` is called by a project's application with an ingest
key (one project, write-only; sessions and cookies play no part and no CSRF applies). Everything
else is a person with a role capability AND project access: reading needs ``read``,
acknowledging/resolving needs ``run``, and ingest keys need ``manage``. A break-glass grant is
read-only, so it can read alerts but not change them."""

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from sentinel_ai.api.deps import (
    get_db,
    request_context,
    require_permission,
    require_project_access,
)
from sentinel_ai.core.config import Settings
from sentinel_ai.core.errors import DomainError, error_body
from sentinel_ai.core.permissions import AccessLevel, Permission
from sentinel_ai.schemas.observability import (
    AlertDetailOut,
    AlertHistoryOut,
    AlertNoteRequest,
    AlertOut,
    CreatedIngestKeyOut,
    CreateIngestKeyRequest,
    GroupDetailOut,
    GroupOut,
    IngestKeyOut,
    IngestResponse,
    SampleOut,
)
from sentinel_ai.services import alerts as alerts_service
from sentinel_ai.services import ingestion
from sentinel_ai.services.audit import RequestContext
from sentinel_ai.services.auth import Principal
from sentinel_ai.services.event_redaction import EventRedactor

ingest_router = APIRouter(tags=["ingest"])
router = APIRouter(tags=["observability"])

_VIEW = [Depends(require_permission(Permission.PROJECT_VIEW))]
_RUN_ROLE = [Depends(require_permission(Permission.PLAN_AND_RUN))]
_MANAGE_ROLE = [Depends(require_permission(Permission.PROJECT_VIEW))]
_READ = Depends(require_project_access(AccessLevel.READ))
_RUN = Depends(require_project_access(AccessLevel.RUN))
_MANAGE = Depends(require_project_access(AccessLevel.MANAGE))
RATE_NOTE_SECONDS = 60.0
_UNAUTHENTICATED = "Authentication required"


class IngestLimits:
    """In-process per-key and per-address limits (state is per API process, like the others)."""

    def __init__(self, settings: Settings) -> None:
        from sentinel_ai.core.ratelimit import RateLimiter

        self.requests = RateLimiter(settings.ingest_requests_per_minute)
        self.events = RateLimiter(settings.ingest_events_per_minute)
        self.failures = RateLimiter(settings.ingest_failed_auth_per_minute)
        self.last_drop_write: dict[str, float] = {}


def _unauthenticated(request: Request) -> JSONResponse:
    return JSONResponse(
        error_body(request, "unauthenticated", _UNAUTHENTICATED),
        status_code=401,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _limited(request: Request) -> JSONResponse:
    return JSONResponse(
        error_body(request, "rate_limited", "Too many requests; slow down"),
        status_code=429,
        headers={"Retry-After": str(int(RATE_NOTE_SECONDS))},
    )


def _bearer(request: Request) -> str | None:
    value = request.headers.get("authorization", "")
    scheme, _, token = value.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


async def _read_body(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise DomainError(413, "payload_too_large", f"Body must be at most {limit} bytes")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise DomainError(413, "payload_too_large", f"Body must be at most {limit} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def _authenticate(request: Request, token: str | None) -> ingestion.KeyAuth | None:
    settings: Settings = request.app.state.settings
    with request.app.state.session_factory() as db:
        auth = ingestion.authenticate(db, settings, token)
        db.commit()
    return auth


def _store(
    request: Request, auth: ingestion.KeyAuth, events: list[Any]
) -> tuple[ingestion.IngestResult | None, bool]:
    """(result, ingestion disabled). Own transaction: commit once per batch."""
    from sentinel_ai.services import observability_policy

    settings: Settings = request.app.state.settings
    redactor: EventRedactor = request.app.state.event_redactor
    with request.app.state.session_factory() as db:
        enabled, _ = observability_policy.load(db, auth.project_id)
        if not enabled:
            return None, True
        try:
            result = ingestion.ingest_batch(db, settings, redactor, auth, events)
            db.commit()
        except Exception:
            db.rollback()
            raise
        return result, False


def _note_rate_drop(request: Request, auth: ingestion.KeyAuth, reason: str, count: int) -> None:
    """Record refused events at most once a minute per key (no DB work per rejected request)."""
    limits: IngestLimits = request.app.state.ingest_limits
    now = time.monotonic()
    key = f"{auth.key_row_id}:{reason}"
    if now - limits.last_drop_write.get(key, 0.0) < RATE_NOTE_SECONDS:
        return
    limits.last_drop_write[key] = now
    if len(limits.last_drop_write) > 10_000:
        limits.last_drop_write.clear()
    with request.app.state.session_factory() as db:
        ingestion.record_drop(db, auth.project_id, reason, count)
        db.commit()


@ingest_router.post("/ingest/events", status_code=202, response_model=IngestResponse)
async def ingest_events(request: Request) -> Any:
    settings: Settings = request.app.state.settings
    limits: IngestLimits = request.app.state.ingest_limits
    peer = request.client.host if request.client else "unknown"
    if limits.failures.blocked(peer):
        return _limited(request)
    auth = await asyncio.to_thread(_authenticate, request, _bearer(request))
    if auth is None:
        limits.failures.allow(peer)
        return _unauthenticated(request)

    key = str(auth.key_row_id)
    if not limits.requests.allow(key):
        await asyncio.to_thread(_note_rate_drop, request, auth, "rate_limited", 1)
        return _limited(request)
    body = await _read_body(request, settings.ingest_max_body_kib * 1024)
    try:
        payload = json.loads(body)
    except (ValueError, RecursionError):
        raise DomainError(422, "validation_failed", "Body must be JSON") from None
    events = (
        payload.get("events") if isinstance(payload, dict) and set(payload) == {"events"} else None
    )
    if not isinstance(events, list) or not events:
        raise DomainError(422, "validation_failed", 'Body must be {"events": [...]}')
    if len(events) > settings.ingest_max_events_per_request:
        raise DomainError(
            422, "validation_failed",
            f"At most {settings.ingest_max_events_per_request} events per request",
        )  # fmt: skip
    if not limits.events.allow(key, len(events)):
        await asyncio.to_thread(_note_rate_drop, request, auth, "rate_limited", len(events))
        return _limited(request)

    result, disabled = await asyncio.to_thread(_store, request, auth, events)
    if disabled or result is None:
        raise DomainError(403, "ingest_disabled", "Event ingestion is not enabled for this project")
    return IngestResponse(
        accepted=result.accepted, dropped={k: v for k, v in result.dropped.items() if v}
    )


# ---- ingest keys (manage) ----------------------------------------------------------------------


def _key_out(row: dict[str, Any]) -> IngestKeyOut:
    return IngestKeyOut(**{k: row[k] for k in IngestKeyOut.model_fields})


@router.post("/projects/{project_id}/ingest-keys", status_code=201, dependencies=_MANAGE_ROLE)
def create_ingest_key(
    project_id: uuid.UUID,
    body: CreateIngestKeyRequest,
    request: Request,
    principal: Principal = _MANAGE,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> CreatedIngestKeyOut:
    row, raw = ingestion.create_key(
        db, ctx, request.app.state.settings, principal.user, project_id,
        label=body.label, expires_in_days=body.expires_in_days,
    )  # fmt: skip
    return CreatedIngestKeyOut(**_key_out(row).model_dump(), key=raw)


@router.get("/projects/{project_id}/ingest-keys", dependencies=_MANAGE_ROLE)
def list_ingest_keys(
    project_id: uuid.UUID, _: Principal = _MANAGE, db: Session = Depends(get_db)
) -> dict[str, list[IngestKeyOut]]:
    return {"items": [_key_out(r) for r in ingestion.list_keys(db, project_id)]}


@router.delete("/projects/{project_id}/ingest-keys/{key_row_id}", dependencies=_MANAGE_ROLE)
def revoke_ingest_key(
    project_id: uuid.UUID,
    key_row_id: uuid.UUID,
    principal: Principal = _MANAGE,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> IngestKeyOut:
    return _key_out(ingestion.revoke_key(db, ctx, principal.user, project_id, key_row_id))


# ---- groups, telemetry, alerts (read) ----------------------------------------------------------


@router.get("/projects/{project_id}/telemetry-status", dependencies=_VIEW)
def telemetry_status(
    project_id: uuid.UUID,
    request: Request,
    _: Principal = _READ,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    now = datetime.now(UTC)
    alerts_service.safe_time_rules(db, request.app.state.settings, project_id, now)
    return alerts_service.telemetry_status(db, project_id, now)


@router.get("/projects/{project_id}/event-groups", dependencies=_VIEW)
def list_event_groups(
    project_id: uuid.UUID,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    _: Principal = _READ,
    db: Session = Depends(get_db),
) -> dict[str, list[GroupOut]]:
    rows = alerts_service.list_groups(db, project_id, limit, offset)
    return {"items": [GroupOut(**{k: r[k] for k in GroupOut.model_fields}) for r in rows]}


@router.get("/projects/{project_id}/event-groups/{group_id}", dependencies=_VIEW)
def get_event_group(
    project_id: uuid.UUID,
    group_id: uuid.UUID,
    request: Request,
    _: Principal = _READ,
    db: Session = Depends(get_db),
) -> GroupDetailOut:
    d = alerts_service.group_detail(db, request.app.state.settings, project_id, group_id)
    base = {k: d[k] for k in GroupOut.model_fields}
    samples = [
        SampleOut(**{k: s[k] for k in SampleOut.model_fields if k in s}) for s in d["samples"]
    ]
    return GroupDetailOut(**base, samples=samples, limits=d["limits"])


def _alert_out(row: dict[str, Any]) -> AlertOut:
    return AlertOut(**{k: row[k] for k in AlertOut.model_fields if k in row})


@router.get("/projects/{project_id}/alerts", dependencies=_VIEW)
def list_alerts(
    project_id: uuid.UUID,
    request: Request,
    status: Annotated[str | None, Query(pattern="^(open|acknowledged|resolved)$")] = None,
    severity: Annotated[str | None, Query(pattern="^(info|low|medium|high)$")] = None,
    rule: Annotated[str | None, Query(max_length=40, pattern="^[a-z_]+$")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    _: Principal = _READ,
    db: Session = Depends(get_db),
) -> dict[str, list[AlertOut]]:
    rows = alerts_service.list_alerts(
        db, request.app.state.settings, project_id, status=status, severity=severity, rule=rule,
        limit=limit, offset=offset,
    )  # fmt: skip
    return {"items": [_alert_out(r) for r in rows]}


@router.get("/projects/{project_id}/alerts/{alert_id}", dependencies=_VIEW)
def get_alert(
    project_id: uuid.UUID,
    alert_id: uuid.UUID,
    request: Request,
    _: Principal = _READ,
    db: Session = Depends(get_db),
) -> AlertDetailOut:
    d = alerts_service.alert_detail(db, request.app.state.settings, project_id, alert_id)
    base = {k: d[k] for k in AlertOut.model_fields if k in d}
    group = GroupOut(**{k: d["group"][k] for k in GroupOut.model_fields}) if d["group"] else None
    return AlertDetailOut(
        **base, history=[AlertHistoryOut(**h) for h in d["history"]], group=group,
        proposal_ids=d["proposal_ids"], telemetry=d["telemetry"], cause_note=d["cause_note"],
    )  # fmt: skip


@router.post("/projects/{project_id}/alerts/{alert_id}/acknowledge", dependencies=_RUN_ROLE)
def acknowledge_alert(
    project_id: uuid.UUID,
    alert_id: uuid.UUID,
    body: AlertNoteRequest,
    principal: Principal = _RUN,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> AlertOut:
    row = alerts_service.acknowledge(db, ctx, principal.user, project_id, alert_id, body.note)
    return _alert_out(row)


@router.post("/projects/{project_id}/alerts/{alert_id}/resolve", dependencies=_RUN_ROLE)
def resolve_alert(
    project_id: uuid.UUID,
    alert_id: uuid.UUID,
    body: AlertNoteRequest,
    principal: Principal = _RUN,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> AlertOut:
    row = alerts_service.resolve(db, ctx, principal.user, project_id, alert_id, body.note)
    return _alert_out(row)
