"""Redaction of text before it is sent to a model (ADR-0010, decision 5).

Layers, in order: (1) the platform's own configured secrets by exact value (database, Redis,
session pepper, the Gemini key and the passwords/users inside URLs; shared with the sandbox
evidence code); (2) credential shapes: ``key=value`` and quoted JSON pairs for secret-like
names, Authorization/Cookie headers, bearer tokens, URL credentials, private-key blocks and
well-known token formats (Google, AWS, GitHub, Slack, JWT, ``sk-`` keys); (3) personal data
(e-mail addresses); (4) long high-entropy tokens that no pattern named; (5) control sequences.

Each replacement is ``[REDACTED:<kind>]`` so the model can tell what was there without seeing
it. Redaction is idempotent and reports counts only, never the removed values. It is a
best-effort filter, not proof that no secret remains: callers still send only focused
excerpts (``evidence_filter``), and the limits are listed in ADR-0010 and Q113.
"""

from collections.abc import Iterable

from sentinel_ai.core.config import Settings
from sentinel_ai.core.text_redaction import prepare_secrets, redact_text
from sentinel_ai.execution.evidence import secret_values
from sentinel_ai.integrations.llm.types import RedactionReport


class PromptRedactor:
    """Implements ``types.Redactor``."""

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        self._secrets = prepare_secrets(secrets)

    @classmethod
    def from_settings(cls, settings: Settings) -> "PromptRedactor":
        return cls(secret_values(settings))

    def redact(self, text: str) -> tuple[str, RedactionReport]:
        text, counts = redact_text(text, self._secrets)
        return text, RedactionReport(counts)
