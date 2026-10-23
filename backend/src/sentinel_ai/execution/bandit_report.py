"""Parse Bandit's JSON report (Stage 10). The report is untrusted data written by a process that
read the project's files: it is size-capped by the framing layer, parsed with ``json`` only,
every field is type-checked, and text is stripped of control characters and clipped.

Bandit's ``code`` snippet is never kept: it can contain the very secret a rule flagged. The
normalized report returned by ``sanitized_report`` holds only the fields below, so evidence
cannot carry project code the scanner merely quoted.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from sentinel_ai.execution.report_common import TEXT_LIMIT as TEXT_LIMIT
from sentinel_ai.execution.report_common import clean_text, safe_path

MAX_FINDINGS = 2000
MAX_ERRORS = 50
_TEST_ID = re.compile(r"B[0-9]{3}")
_LEVELS = {"LOW": "low", "MEDIUM": "medium", "HIGH": "high"}
# Rules whose message quotes the suspected secret itself.
_QUOTES_VALUE = frozenset({"B105", "B106", "B107"})
_QUOTED = re.compile(r"(['\"]).*?\1")

LIMITATIONS = (
    "Static pattern match on source text; nothing was executed, so exploitability is not "
    "established. Bandit analyses Python only, and a clean result does not mean the code is secure."
)


class InvalidReport(ValueError):
    """The report is not usable (message is safe to show)."""


@dataclass(frozen=True)
class BanditFinding:
    rule_id: str
    rule_name: str
    severity: str  # info | low | medium | high
    confidence: str  # low | medium | high
    path: str
    line: int
    message: str
    cwe: int | None
    fingerprint: str


@dataclass(frozen=True)
class ParsedBandit:
    findings: tuple[BanditFinding, ...]
    errors: tuple[str, ...]
    truncated: bool
    lines_scanned: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


_text = clean_text
_path = safe_path


def _level(value: Any, *, default: str) -> str:
    return _LEVELS.get(value.upper(), default) if isinstance(value, str) else default


def _fingerprint(rule_id: str, path: str, message: str, index: int) -> str:
    """Stable across line moves: tool, rule, file, normalized message and the occurrence
    number of that combination inside the file (ordered by line)."""
    norm = " ".join(message.split())
    digest = hashlib.sha256(f"bandit\0{rule_id}\0{path}\0{norm}\0{index}".encode()).hexdigest()
    return f"bandit:{digest[:40]}"


def parse(raw: bytes) -> ParsedBandit:
    try:
        doc = json.loads(raw)
    except (ValueError, RecursionError):
        raise InvalidReport("the report is not valid JSON") from None
    if not isinstance(doc, dict) or not isinstance(doc.get("results"), list):
        raise InvalidReport("the report does not have the expected structure")
    rows: list[tuple[str, str, int, dict[str, Any]]] = []
    for item in doc["results"]:
        if not isinstance(item, dict):
            continue
        rule_id = item.get("test_id")
        line = item.get("line_number")
        if not isinstance(rule_id, str) or not _TEST_ID.fullmatch(rule_id):
            continue
        if not isinstance(line, int) or isinstance(line, bool) or not 0 < line < 10_000_000:
            line = 1
        rows.append((_path(item.get("filename")), rule_id, line, item))
    truncated = len(rows) > MAX_FINDINGS
    rows.sort(key=lambda r: (r[0], r[2], r[1]))
    seen: dict[tuple[str, str, str], int] = {}
    findings: list[BanditFinding] = []
    for path, rule_id, line, item in rows[:MAX_FINDINGS]:
        message = _text(item.get("issue_text"))
        if rule_id in _QUOTES_VALUE:
            message = _QUOTED.sub("'<redacted>'", message)
        key = (path, rule_id, " ".join(message.split()))
        index = seen.get(key, 0)
        seen[key] = index + 1
        cwe = item.get("issue_cwe")
        cwe_id = cwe.get("id") if isinstance(cwe, dict) else None
        findings.append(
            BanditFinding(
                rule_id=rule_id,
                rule_name=_text(item.get("test_name"), 100),
                severity=_level(item.get("issue_severity"), default="low"),
                confidence=_level(item.get("issue_confidence"), default="low"),
                path=path,
                line=line,
                message=message,
                cwe=cwe_id if isinstance(cwe_id, int) and not isinstance(cwe_id, bool) else None,
                fingerprint=_fingerprint(rule_id, path, message, index),
            )
        )
    raw_errors = doc.get("errors")
    errors = tuple(
        _text(e.get("reason") if isinstance(e, dict) else e, 200)
        for e in (raw_errors if isinstance(raw_errors, list) else [])[:MAX_ERRORS]
    )
    metrics = doc.get("metrics")
    totals = metrics.get("_totals") if isinstance(metrics, dict) else None
    scanned = totals.get("loc") if isinstance(totals, dict) else None
    lines = scanned if isinstance(scanned, int) and not isinstance(scanned, bool) else None
    return ParsedBandit(tuple(findings), errors, truncated, lines_scanned=lines)


def sanitized_report(parsed: ParsedBandit) -> bytes:
    """What is stored as evidence: the validated fields only, never Bandit's code snippets."""
    doc = {
        "tool": "bandit",
        "results": [
            {
                "test_id": f.rule_id,
                "test_name": f.rule_name,
                "issue_severity": f.severity,
                "issue_confidence": f.confidence,
                "filename": f.path,
                "line_number": f.line,
                "issue_text": f.message,
                "cwe": f.cwe,
                "fingerprint": f.fingerprint,
            }  # fmt: skip
            for f in parsed.findings
        ],
        "errors": list(parsed.errors),
        "truncated": parsed.truncated,
        "note": "Code snippets are intentionally omitted.",
    }
    return json.dumps(doc, indent=2, sort_keys=True).encode()
