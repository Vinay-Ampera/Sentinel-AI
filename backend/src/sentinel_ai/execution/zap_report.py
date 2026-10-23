"""Parse OWASP ZAP's traditional JSON report (Stage 10). Untrusted data: see ``report_common``.

The report was produced by a process that talked to a remote server, so it carries attacker
influenced text. Kept: alert id and name, risk, confidence, CWE, the method, path (never the
query string or fragment) and parameter *name* of each instance, and a markup-free description
and solution. Dropped: ``evidence``, ``attack``, ``otherinfo`` and request/response data, which
can quote the target's responses (tokens, personal data). Instances whose host is not the
authorized target's are ignored and counted as an error, so a redirect cannot widen a scan's
reach in the recorded findings.
"""

import re
from urllib.parse import urlsplit

from sentinel_ai.execution.interface import FindingResult
from sentinel_ai.execution.report_common import (
    as_int,
    clean_text,
    cwe_number,
    fingerprint,
    strip_markup,
)
from sentinel_ai.execution.scan_report import (
    MAX_ERRORS,
    MAX_FINDINGS,
    InvalidReport,
    ParsedScan,
    load_object,
)

TOOL = "zap"
MAX_INSTANCES_PER_ALERT = 20
_RISK = {0: "info", 1: "low", 2: "medium", 3: "high"}
_CONFIDENCE = {0: "low", 1: "low", 2: "medium", 3: "high", 4: "high"}  # ZAP: 0 false positive
_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,59}")
_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})
_PATH = re.compile(r"/[A-Za-z0-9._~!$&'()*+,;=:@%/-]{0,400}|/")
_PARAM = re.compile(r"[A-Za-z0-9_.\[\]-]{1,60}")

LIMITATIONS_BASELINE = (
    "Passive observation of the responses a short crawl received; no attack payloads were sent. "
    "It sees only what the crawl reached, so an empty or short alert list does not mean the "
    "application is secure, and alerts are leads that need a person's confirmation."
)
LIMITATIONS_ACTIVE = (
    "Automated attack-style requests against what a bounded crawl reached. Alerts are heuristic "
    "and can be false positives; coverage is partial, authenticated areas are not tested, and "
    "absence of an alert does not mean the application is secure."
)


def parse(raw: bytes, *, host: str, active: bool = False) -> ParsedScan:
    doc = load_object(raw)
    sites = doc.get("site")
    if isinstance(sites, dict):
        sites = [sites]
    if not isinstance(sites, list):
        raise InvalidReport("the report does not have the expected structure")
    out_of_scope = 0
    seen: set[str] = set()
    found: list[FindingResult] = []
    for site in sites:
        alerts = site.get("alerts") if isinstance(site, dict) else None
        for alert in alerts if isinstance(alerts, list) else []:
            if not isinstance(alert, dict):
                continue
            ref = alert.get("alertRef") or alert.get("pluginid")
            ref = str(ref) if isinstance(ref, (str, int)) and not isinstance(ref, bool) else ""
            name = clean_text(alert.get("name") or alert.get("alert"), 200)
            if not _REF.fullmatch(ref) or not name:
                continue
            risk = _RISK.get(as_int(alert.get("riskcode"), low=0, high=3) or 0, "info")
            conf = _CONFIDENCE.get(as_int(alert.get("confidence"), low=0, high=4) or 0, "low")
            desc = strip_markup(alert.get("desc"), 400)
            fix = strip_markup(alert.get("solution"), 200)
            message = f"{desc} Fix: {fix}".strip() if fix else desc
            cwe = cwe_number(alert.get("cweid"))
            instances = alert.get("instances")
            for inst in (instances if isinstance(instances, list) else [])[
                :MAX_INSTANCES_PER_ALERT
            ]:
                if not isinstance(inst, dict) or not isinstance(inst.get("uri"), str):
                    continue
                try:
                    parts = urlsplit(inst["uri"])
                    inst_host = (parts.hostname or "").lower()
                except ValueError:
                    continue
                if parts.scheme not in ("http", "https") or inst_host != host:
                    out_of_scope += 1
                    continue
                path = parts.path or "/"
                method = inst.get("method")
                method = method if method in _METHODS else "GET"
                param = inst.get("param")
                param = param if isinstance(param, str) and _PARAM.fullmatch(param) else ""
                if not _PATH.fullmatch(path):
                    continue
                port = f":{parts.port}" if parts.port else ""
                component = f"{method} {parts.scheme}://{inst_host}{port}{path}"
                fp = fingerprint(TOOL, ref, method, inst_host, path, param)
                if fp in seen:
                    continue
                seen.add(fp)
                found.append(
                    FindingResult(
                        tool=TOOL,
                        rule_id=ref,
                        title=f"{name} ({ref})"[:300],
                        severity=risk,
                        confidence=conf,
                        path=path[:400],
                        line=None,
                        message=message + (f" Parameter: {param}." if param else ""),
                        fingerprint=fp,
                        cwe=cwe,
                        category="dynamic",
                        component=component[:400],
                    )  # fmt: skip
                )
    found.sort(key=lambda f: (f.component or "", f.rule_id))
    truncated = len(found) > MAX_FINDINGS
    errors: tuple[str, ...] = ()
    if out_of_scope:
        errors = (f"{out_of_scope} alert instance(s) outside the authorized host were ignored",)
    errors = errors[:MAX_ERRORS]
    return ParsedScan(
        TOOL, tuple(found[:MAX_FINDINGS]), errors, truncated,
        LIMITATIONS_ACTIVE if active else LIMITATIONS_BASELINE, always_partial=True,
    )  # fmt: skip
