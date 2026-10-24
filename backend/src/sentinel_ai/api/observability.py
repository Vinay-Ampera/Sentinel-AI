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
from collections.abc import Callable
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
from sentinel_ai.core import clientip, limiters
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
from sentinel_ai.services import ingestion, otlp, traces
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
KNOWN_KEY_SECONDS = 300.0
_UNAUTHENTICATED = "Authentication required"


class IngestLimits:
    """Per-key and per-address limits. In process by default; with ``RATE_LIMIT_BACKEND=redis``
    the counts and the "authenticated recently" markers are shared by every API process."""

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.requests = limiters.make_limiter(
            client, "ingest_requests", settings.ingest_requests_per_minute
        )
        self.events = limiters.make_limiter(
            client, "ingest_events", settings.ingest_events_per_minute
        )
        self.failures = limiters.make_limiter(
            client, "ingest_failures", settings.ingest_failed_auth_per_minute
        )
        self.last_drop_write: dict[str, float] = {}
        self._known = limiters.make_flags(client, "ingest_known_keys", KNOWN_KEY_SECONDS)

    def remember(self, key_id: str | None) -> None:
        if key_id is not None:
            self._known.set(key_id)

    def is_known(self, key_id: str | None) -> bool:
        return bool(key_id) and self._known.has(str(key_id))


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


def _client(request: Request) -> str:
    """Address used to throttle failed keys: the direct peer, or the forwarded client when the
    peer is a configured trusted proxy (``TRUSTED_PROXY_CIDRS``; core/clientip.py)."""
    settings: Settings = request.app.state.settings
    peer = request.client.host if request.client else None
    trusted = clientip.parse_networks(settings.trusted_proxy_cidrs)
    return (
        clientip.client_ip(peer, request.headers.get("x-forwarded-for"), trusted)
        or peer
        or "unknown"
    )


async def _ingest(
    request: Request, extract: Callable[[Any, int], list[Any] | None], shape: str
) -> Any:
    """Shared by the native and the OTLP endpoint: key authentication, limits, then the same
    validation, redaction and grouping. ``extract`` turns the parsed JSON into event dicts."""
    settings: Settings = request.app.state.settings
    limits: IngestLimits = request.app.state.ingest_limits
    peer = _client(request)
    token = _bearer(request)
    key_id = ingestion._split(token) if token else None
    # A sender that authenticated recently keeps working while its address is being throttled
    # for failures (a shared proxy address); it is still fully authenticated below.
    if limits.failures.blocked(peer) and not limits.is_known(key_id):
        return _limited(request)
    auth = await asyncio.to_thread(_authenticate, request, token)
    if auth is None:
        limits.failures.allow(peer)
        return _unauthenticated(request)
    limits.remember(key_id)

    key = str(auth.key_row_id)
    if not limits.requests.allow(key):
        await asyncio.to_thread(_note_rate_drop, request, auth, "rate_limited", 1)
        return _limited(request)
    body = await _read_body(request, settings.ingest_max_body_kib * 1024)
    try:
        payload = json.loads(body)
    except (ValueError, RecursionError):
        raise DomainError(422, "validation_failed", "Body must be JSON") from None
    cap = settings.ingest_max_events_per_request
    events = extract(payload, cap)
    if not isinstance(events, list) or not events:
        raise DomainError(422, "validation_failed", f"Body must be {shape}")
    if len(events) > cap:
        raise DomainError(422, "validation_failed", f"At most {cap} events per request")
    if not limits.events.allow(key, len(events)):
        await asyncio.to_thread(_note_rate_drop, request, auth, "rate_limited", len(events))
        return _limited(request)

    result, disabled = await asyncio.to_thread(_store, request, auth, events)
    if disabled or result is None:
        raise DomainError(403, "ingest_disabled", "Event ingestion is not enabled for this project")
    return result


def _native_events(payload: Any, _cap: int) -> list[Any] | None:
    if (
        isinstance(payload, dict)
        and set(payload) == {"events"}
        and isinstance(payload["events"], list)
    ):
        return payload["events"]
    return None


@ingest_router.post("/ingest/events", status_code=202, response_model=IngestResponse)
async def ingest_events(request: Request) -> Any:
    result = await _ingest(request, _native_events, '{"events": [...]}')
    if isinstance(result, JSONResponse):
        return result
    return IngestResponse(
        accepted=result.accepted, dropped={k: v for k, v in result.dropped.items() if v}
    )


@ingest_router.post("/ingest/otlp/v1/logs")
async def ingest_otlp_logs(request: Request) -> Any:
    """OpenTelemetry OTLP/HTTP logs, JSON encoding only. Point an OTLP exporter at
    ``<api>/api/v1/ingest/otlp`` with the header ``Authorization=Bearer <ingest key>``. The
    reply is the OTLP success shape; records that were dropped are reported as rejected."""
    kind = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if kind != "application/json":
        raise DomainError(
            415, "unsupported_media_type", "Only OTLP/HTTP with the JSON encoding is supported"
        )
    result = await _ingest(request, otlp.logs_to_events, 'an OTLP "resourceLogs" document')
    if isinstance(result, JSONResponse):
        return result
    rejected = sum(v for k, v in result.dropped.items() if k not in ("level_below_threshold",))
    reply: dict[str, Any] = {}
    if rejected:
        reply["partialSuccess"] = {
            "rejectedLogRecords": rejected,
            "errorMessage": ", ".join(f"{k}: {v}" for k, v in result.dropped.items() if v),
        }
    return JSONResponse(reply, status_code=200)


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


@router.get("/projects/{project_id}/traces/{trace_id}", dependencies=_VIEW)
def get_trace(
    project_id: uuid.UUID,
    trace_id: str,
    request: Request,
    _: Principal = _READ,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return traces.trace_view(db, request.app.state.settings, project_id, trace_id)
