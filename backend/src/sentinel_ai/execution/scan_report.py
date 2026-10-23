"""The common shape of a parsed scanner report (Stage 10; Semgrep, dependency audit, ZAP).

Bandit predates this and keeps its own ``bandit_report.ParsedBandit``. A parser never raises
anything but ``InvalidReport``, returns findings that are already normalized, and builds the
sanitized evidence document from validated fields only (never the tool's code snippets,
request/response bodies or query strings).
"""

import json
from dataclasses import dataclass
from typing import Any

from sentinel_ai.execution.interface import FindingResult

MAX_FINDINGS = 2000
MAX_ERRORS = 50


class InvalidReport(ValueError):
    """The report is not usable (message is safe to show)."""


@dataclass(frozen=True)
class ParsedScan:
    tool: str
    findings: tuple[FindingResult, ...]
    errors: tuple[str, ...]
    truncated: bool
    limitations: str
    always_partial: bool = False  # a scan that can never prove absence (dynamic scans)
    lines_scanned: int | None = None
    extra: tuple[tuple[str, Any], ...] = ()

    @property
    def complete(self) -> bool:
        return not (self.errors or self.truncated or self.always_partial)


def sanitized(parsed: ParsedScan) -> bytes:
    """What is stored as evidence: validated fields only, plus the facts about the run."""
    doc = {
        "tool": parsed.tool,
        "results": [
            {
                "rule_id": f.rule_id,
                "title": f.title,
                "severity": f.severity,
                "confidence": f.confidence,
                "category": f.category,
                "path": f.path,
                "line": f.line,
                "component": f.component,
                "cwe": f.cwe,
                "aliases": list(f.aliases),
                "message": f.message,
                "fingerprint": f.fingerprint,
            }  # fmt: skip
            for f in parsed.findings
        ],
        "errors": list(parsed.errors),
        "truncated": parsed.truncated,
        "complete": parsed.complete,
        "details": dict(parsed.extra),
        "note": "Code snippets, request/response bodies and query strings are omitted.",
    }
    return json.dumps(doc, indent=2, sort_keys=True).encode()


def load_object(raw: bytes) -> dict[str, Any]:
    try:
        doc = json.loads(raw)
    except (ValueError, RecursionError):
        raise InvalidReport("the report is not valid JSON") from None
    if not isinstance(doc, dict):
        raise InvalidReport("the report does not have the expected structure")
    return doc
