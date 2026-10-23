"""Parse Semgrep's JSON report (Stage 10). Untrusted data: see ``report_common``.

Semgrep's ``extra.lines`` (the matched source text) is never kept: it can contain the very
secret a rule flagged. Rule ids are reduced to the rule's own id (Semgrep prefixes them with
the directory of the rules it loaded), severity comes from the rule (ERROR/WARNING/INFO) and
confidence from the rule's own metadata (``low`` when it declares none).
"""

import re
from typing import Any

from sentinel_ai.execution.interface import FindingResult
from sentinel_ai.execution.report_common import (
    as_int,
    clean_text,
    cwe_number,
    fingerprint,
    safe_path,
)
from sentinel_ai.execution.scan_report import (
    MAX_ERRORS,
    MAX_FINDINGS,
    InvalidReport,
    ParsedScan,
    load_object,
)

TOOL = "semgrep"
_SEVERITY = {"ERROR": "high", "WARNING": "medium", "INFO": "low"}
_CONFIDENCE = {"LOW": "low", "MEDIUM": "medium", "HIGH": "high"}
_RULE_ID = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,199}")
_OWN_PREFIX = "sentinel"

LIMITATIONS = (
    "Pattern match from a small bundled rule set on source text; nothing was executed, so "
    "exploitability is not established. Only the languages and patterns those rules cover are "
    "checked, and a clean result does not mean the code is secure."
)


def rule_id_of(check_id: str) -> str | None:
    """``opt.sentinel.semgrep-rules.sentinel.python.os-system`` -> ``sentinel.python.os-system``."""
    segs = check_id.split(".")
    if _OWN_PREFIX in segs:
        segs = segs[len(segs) - 1 - segs[::-1].index(_OWN_PREFIX) :]
    rule = ".".join(segs)
    return rule if _RULE_ID.fullmatch(rule) else None


def parse(raw: bytes) -> ParsedScan:
    doc = load_object(raw)
    if not isinstance(doc.get("results"), list):
        raise InvalidReport("the report does not have the expected structure")
    rows: list[tuple[str, str, int, dict[str, Any]]] = []
    for item in doc["results"]:
        if not isinstance(item, dict) or not isinstance(item.get("check_id"), str):
            continue
        rule = rule_id_of(item["check_id"])
        if rule is None:
            continue
        start = item.get("start")
        line = as_int(start.get("line") if isinstance(start, dict) else None, low=1, high=9_999_999)
        rows.append((safe_path(item.get("path")), rule, line or 1, item))
    truncated = len(rows) > MAX_FINDINGS
    rows.sort(key=lambda r: (r[0], r[2], r[1]))
    seen: dict[tuple[str, str, str], int] = {}
    findings: list[FindingResult] = []
    for path, rule, line, item in rows[:MAX_FINDINGS]:
        extra: dict[str, Any] = item["extra"] if isinstance(item.get("extra"), dict) else {}
        meta: dict[str, Any] = extra["metadata"] if isinstance(extra.get("metadata"), dict) else {}
        message = clean_text(extra.get("message"))
        key = (path, rule, " ".join(message.split()))
        index = seen.get(key, 0)
        seen[key] = index + 1
        sev = extra.get("severity")
        conf = meta.get("confidence")
        findings.append(
            FindingResult(
                tool=TOOL,
                rule_id=rule,
                title=f"{rule.rsplit('.', 1)[-1].replace('-', ' ')} ({rule})"[:300],
                severity=_SEVERITY.get(sev.upper(), "low") if isinstance(sev, str) else "low",
                confidence=_CONFIDENCE.get(conf.upper(), "low") if isinstance(conf, str) else "low",
                path=path,
                line=line,
                message=message,
                fingerprint=fingerprint(TOOL, rule, path, " ".join(message.split()), index),
                cwe=cwe_number(meta.get("cwe")),
            )
        )
    raw_errors = doc.get("errors")
    errors = tuple(
        clean_text(
            (e.get("long_msg") or e.get("short_msg") or e.get("type"))
            if isinstance(e, dict)
            else e,
            200,
        )
        for e in (raw_errors if isinstance(raw_errors, list) else [])[:MAX_ERRORS]
    )
    paths = doc.get("paths")
    scanned = paths.get("scanned") if isinstance(paths, dict) else None
    skipped = paths.get("skipped") if isinstance(paths, dict) else None
    extra_info = (
        ("files_scanned", len(scanned) if isinstance(scanned, list) else None),
        ("files_skipped", len(skipped) if isinstance(skipped, list) else None),
    )
    return ParsedScan(TOOL, tuple(findings), errors, truncated, LIMITATIONS, extra=extra_info)
