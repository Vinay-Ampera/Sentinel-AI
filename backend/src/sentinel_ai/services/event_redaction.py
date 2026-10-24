"""Redaction of ingested events before anything is stored (ADR-0011, decision 4).

Uses the shared pattern set (``core.text_redaction``, the same one the model gateway uses) plus
configured secret values, and blanks attribute values whose *key* names a credential. Returns
counts only. The raw payload is never kept: callers redact first and store the result."""

from collections import Counter
from typing import Any

from sentinel_ai.core.config import Settings
from sentinel_ai.core.text_redaction import prepare_secrets, redact_text
from sentinel_ai.execution.evidence import secret_values

DENY_KEY_WORDS = (
    "password", "passwd", "secret", "token", "authorization", "cookie", "session", "api_key",
    "apikey", "api-key", "private_key", "credential", "ssn", "card",
)  # fmt: skip
ATTRIBUTE_TAG = "[REDACTED:attribute]"


class EventRedactor:
    def __init__(self, secrets: tuple[str, ...] = ()) -> None:
        self._secrets = prepare_secrets(secrets)

    @classmethod
    def from_settings(cls, settings: Settings) -> "EventRedactor":
        return cls(secret_values(settings))

    def text(self, value: str, counts: Counter[str]) -> str:
        out, found = redact_text(value, self._secrets)
        counts.update(found)
        return out

    def attributes(self, attrs: dict[str, Any], counts: Counter[str]) -> dict[str, Any]:
        clean: dict[str, Any] = {}
        for key, value in attrs.items():
            if any(word in key.lower() for word in DENY_KEY_WORDS):
                counts["attribute_key"] += 1
                clean[key] = ATTRIBUTE_TAG
            elif isinstance(value, str):
                clean[key] = self.text(value, counts)[:256]
            else:
                clean[key] = value
        return clean
