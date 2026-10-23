"""Turning sandbox output into stored evidence (Stage 8).

Everything a sandbox prints is untrusted data. It is decoded safely, stripped of control
sequences, redacted of configured secrets and common credential shapes, capped, and stored
under server-chosen names. It never decides a result: status comes from the container's
exit state as read by the host.
"""

import json
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit

from pydantic import SecretStr

from sentinel_ai.core.config import Settings
from sentinel_ai.execution.interface import EvidenceItem

REDACTED = "[REDACTED]"
MIN_SECRET_LEN = 6
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]|\x1b\[[0-9;?]*[ -/]*[@-~]")
_PATTERNS = (
    (re.compile(r"(?i)\b(password|passwd|secret|token|api[_-]?key|authorization)(\s*[=:]\s*)\S+"), r"\1\2" + REDACTED),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"), "Bearer " + REDACTED),
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@"), r"\1" + REDACTED + "@"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(-----END [A-Z ]*PRIVATE KEY-----|$)", re.S), REDACTED),
)  # fmt: skip


def secret_values(settings: Settings) -> tuple[str, ...]:
    """Every configured secret (and the password inside each URL) that must never appear."""
    raw: list[str] = []
    for value in (
        settings.database_url,
        settings.redis_url,
        settings.session_token_pepper,
        settings.gemini_api_key,
    ):
        if isinstance(value, SecretStr):
            text = value.get_secret_value()
            raw.append(text)
            parts = urlsplit(text)
            raw.extend(p for p in (parts.password, parts.username) if p)
    return tuple(sorted({v for v in raw if len(v) >= MIN_SECRET_LEN}, key=len, reverse=True))


def redact(data: bytes, secrets: Iterable[str]) -> bytes:
    text = data.decode("utf-8", errors="replace")
    for secret in secrets:
        if len(secret) >= MIN_SECRET_LEN:
            text = text.replace(secret, REDACTED)
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return _CONTROL.sub("", text).encode("utf-8")


def cap(data: bytes, limit: int) -> tuple[bytes, bool]:
    if len(data) <= limit:
        return data, False
    return data[:limit], True


def log_item(
    name: str, raw: bytes, secrets: Iterable[str], limit: int, truncated: bool
) -> EvidenceItem:
    clean, cut = cap(redact(raw, secrets), limit)
    if truncated or cut:
        clean += b"\n[output truncated by Sentinel]\n"
    return EvidenceItem(name, "log", "text/plain; charset=utf-8", clean)


def manifest_item(manifest: dict[str, Any]) -> EvidenceItem:
    body = json.dumps(manifest, indent=2, sort_keys=True, default=str).encode()
    return EvidenceItem("manifest.json", "report", "application/json", body)
