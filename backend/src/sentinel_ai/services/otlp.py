"""Mapping OpenTelemetry (OTLP/HTTP, JSON encoding) log records to Sentinel events (ADR-0011).

This is a *translation only*: the result is the same ``EventIn`` shaped dicts the native
ingestion endpoint takes, and they go through the same key authentication, limits, schema
validation, redaction and grouping. Nothing here trusts the payload: unknown fields are
ignored, values are bounded, and a record that cannot be mapped is passed on as an invalid
event so it is counted as dropped rather than lost silently. Protobuf encoding is not accepted."""

import json
import re
from datetime import UTC, datetime
from typing import Any

MAX_ATTRIBUTES = 20
_ENV = {
    "production": "production", "prod": "production", "staging": "staging", "stage": "staging",
    "development": "development", "dev": "development", "local": "local", "test": "development",
}  # fmt: skip
_KEY_BAD = re.compile(r"[^a-z0-9_.-]")
_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_HEX16 = re.compile(r"^[0-9a-f]{16}$")


def severity_level(number: Any, text: Any) -> str:
    """OTLP severity numbers: 1-4 trace, 5-8 debug, 9-12 info, 13-16 warn, 17-20 error,
    21-24 fatal. The text is used only when the number is missing."""
    if isinstance(number, int) and not isinstance(number, bool) and 1 <= number <= 24:
        if number >= 21:
            return "fatal"
        if number >= 17:
            return "error"
        return "warning" if number >= 13 else "info" if number >= 9 else "debug"
    name = str(text or "").strip().lower()
    if name in ("fatal", "critical", "emergency", "alert"):
        return "fatal"
    if name in ("error", "err", "severe"):
        return "error"
    if name in ("warn", "warning"):
        return "warning"
    return "info"  # unknown severity is below the floor, never promoted to an error


def any_value(value: Any) -> Any:
    """The scalar of an OTLP AnyValue; structured values become bounded JSON text."""
    if not isinstance(value, dict):
        return None
    if "stringValue" in value:
        return str(value["stringValue"])
    if "boolValue" in value:
        return bool(value["boolValue"])
    if "intValue" in value:
        try:
            return int(value["intValue"])  # JSON encodes 64-bit integers as strings
        except (TypeError, ValueError):
            return None
    if "doubleValue" in value:
        try:
            number = float(value["doubleValue"])
        except (TypeError, ValueError):
            return None
        return number if number == number and abs(number) != float("inf") else None
    for key in ("arrayValue", "kvlistValue"):
        if key in value:
            return json.dumps(value[key], separators=(",", ":"))[:256]
    return None


def attributes(items: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str):
            continue
        value = any_value(item.get("value"))
        if value is not None:
            out[item["key"]] = value
    return out


def _attr_key(name: str) -> str:
    return _KEY_BAD.sub("_", name.lower())[:40] or "attr"


def _time(nanos: Any) -> str | None:
    try:
        seconds = int(nanos) / 1_000_000_000
        return datetime.fromtimestamp(seconds, UTC).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _hex(value: Any, pattern: re.Pattern[str]) -> str | None:
    text = str(value or "").lower()
    return text if pattern.match(text) and set(text) != {"0"} else None


def map_record(resource: dict[str, Any], record: Any) -> dict[str, Any]:
    """One log record as a native event dict (it may still be invalid; validation counts it)."""
    if not isinstance(record, dict):
        return {}
    attrs = attributes(record.get("attributes"))
    body = any_value(record.get("body"))
    exc_type = attrs.pop("exception.type", None)
    exc_message = attrs.pop("exception.message", None)
    stack = attrs.pop("exception.stacktrace", None)
    message = str(body) if body not in (None, "") else str(exc_message or "")
    event: dict[str, Any] = {
        "level": severity_level(record.get("severityNumber"), record.get("severityText")),
        "service": str(resource.get("service.name") or "unknown_service"),
        "message": message[:2048],
    }
    env = _ENV.get(str(resource.get("deployment.environment") or "").lower())
    event["environment"] = env or "unknown"
    if exc_type:
        event["error_type"] = str(exc_type)[:128]
    if stack:
        event["stack"] = str(stack)[:8192]
    if resource.get("service.version"):
        event["release"] = str(resource["service.version"])[:64]
    stamp = _time(record.get("timeUnixNano") or record.get("observedTimeUnixNano"))
    if stamp:
        event["timestamp"] = stamp
    trace, span = _hex(record.get("traceId"), _HEX32), _hex(record.get("spanId"), _HEX16)
    if trace:
        event["trace_id"] = trace
    if span:
        event["span_id"] = span
    kept = {_attr_key(k): v for k, v in list(attrs.items())[:MAX_ATTRIBUTES]}
    if kept:
        event["attributes"] = {k: (v[:256] if isinstance(v, str) else v) for k, v in kept.items()}
    return event


def logs_to_events(payload: Any, limit: int) -> list[dict[str, Any]] | None:
    """All records of an ``ExportLogsServiceRequest`` JSON body, or None when the body is not
    one. More than ``limit`` records is refused by the caller (it gets ``limit + 1`` back)."""
    if not isinstance(payload, dict) or not isinstance(payload.get("resourceLogs"), list):
        return None
    events: list[dict[str, Any]] = []
    for rl in payload["resourceLogs"]:
        if not isinstance(rl, dict):
            continue
        resource = attributes((rl.get("resource") or {}).get("attributes"))
        for scope in rl.get("scopeLogs") or []:
            if not isinstance(scope, dict):
                continue
            for record in scope.get("logRecords") or []:
                events.append(map_record(resource, record))
                if len(events) > limit:
                    return events
    return events
