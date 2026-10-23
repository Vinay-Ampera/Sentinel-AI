"""Parse the offline dependency-audit report (Stage 10). Untrusted data: see ``report_common``.

The report comes from ``sandbox/dep_audit.py``, which matched locked versions against the
advisory bundle baked into the image. One finding is made per (ecosystem, package, version,
advisory) even if several lockfiles pin that version; the finding's confidence is ``high`` only
for the version match itself. Whether the vulnerable code is *reachable* is not assessed.
"""

import re
from dataclasses import replace
from typing import Any

from sentinel_ai.execution.interface import FindingResult
from sentinel_ai.execution.report_common import clean_text, fingerprint, safe_path
from sentinel_ai.execution.scan_report import (
    MAX_ERRORS,
    MAX_FINDINGS,
    InvalidReport,
    ParsedScan,
    load_object,
)

TOOL = "dependency_audit"
_ECOSYSTEMS = {"PyPI": "pypi", "npm": "npm"}
_SEVERITIES = frozenset({"low", "medium", "high", "critical"})
_PACKAGE = re.compile(r"[@A-Za-z0-9][A-Za-z0-9._~/@+-]{0,213}")
_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+!~-]{0,99}")
_ADVISORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{2,59}")

LIMITATIONS = (
    "The locked version falls in an advisory's affected range. Reachability is not assessed: the "
    "vulnerable code may never be called. Coverage is limited to the supported lockfiles and to "
    "the advisory data baked into the sandbox image on the date shown; newer advisories are not "
    "known."
)


def _names(values: Any, limit: int = 10) -> list[str]:
    return [v for v in (values if isinstance(values, list) else [])[:limit]
            if isinstance(v, str) and _ADVISORY.fullmatch(v)]  # fmt: skip


def parse(raw: bytes) -> ParsedScan:
    doc = load_object(raw)
    if doc.get("tool") != TOOL or not isinstance(doc.get("results"), list):
        raise InvalidReport("the report does not have the expected structure")
    lockfiles = [safe_path(p) for p in (doc.get("lockfiles") or [])[:50] if isinstance(p, str)]
    unsupported = [safe_path(p) for p in (doc.get("unsupported_lockfiles") or [])[:50]]
    merged: dict[str, FindingResult] = {}
    files: dict[str, set[str]] = {}
    for item in doc["results"]:
        if not isinstance(item, dict):
            continue
        raw_eco = item.get("ecosystem")
        eco = _ECOSYSTEMS.get(raw_eco) if isinstance(raw_eco, str) else None
        pkg, ver, adv = item.get("package"), item.get("version"), item.get("advisory_id")
        if (
            eco is None
            or not isinstance(pkg, str) or not _PACKAGE.fullmatch(pkg)
            or not isinstance(ver, str) or not _VERSION.fullmatch(ver)
            or not isinstance(adv, str) or not _ADVISORY.fullmatch(adv)
        ):  # fmt: skip
            continue
        norm = re.sub(r"[-_.]+", "-", pkg).lower() if eco == "pypi" else pkg
        fp = fingerprint(TOOL, eco, norm, ver, adv)
        lock = safe_path(item.get("lockfile"))
        files.setdefault(fp, set()).add(lock)
        if fp in merged:
            continue
        sev = item.get("severity")
        fixed = ", ".join(_names(item.get("fixed"), 5))
        summary = clean_text(item.get("summary"), 300)
        aliases = tuple(dict.fromkeys([adv, *_names(item.get("aliases"))]))
        cwes = item.get("cwes")
        cwe = next(
            (
                c
                for c in (cwes if isinstance(cwes, list) else [])
                if isinstance(c, int) and 0 < c < 100000
            ),
            None,
        )
        merged[fp] = FindingResult(
            tool=TOOL, rule_id=adv, title=f"{pkg} {ver}: {adv}"[:300],
            severity=sev if sev in _SEVERITIES else "medium", confidence="high",
            path=lock, line=None,
            message=(summary + (f" Fixed in: {fixed}." if fixed else "")).strip(),
            fingerprint=fp, cwe=cwe, category="dependency",
            component=f"{eco}:{pkg}@{ver}", aliases=aliases,
        )  # fmt: skip
    ordered = sorted(merged.values(), key=lambda f: (f.component or "", f.rule_id))
    truncated = len(ordered) > MAX_FINDINGS
    findings = []
    for f in ordered[:MAX_FINDINGS]:
        locks = sorted(files[f.fingerprint])
        extra = f" Also pinned in: {', '.join(locks[1:4])}." if len(locks) > 1 else ""
        findings.append(replace(f, path=locks[0], message=f.message + extra))
    errors = tuple(
        clean_text(e, 200) for e in (doc.get("errors") or [])[:MAX_ERRORS] if isinstance(e, str)
    ) + tuple(f"{p}: lockfile format not supported, not audited" for p in unsupported)
    data = doc.get("advisory_data")
    info = tuple(
        (eco, clean_text((d or {}).get("fetched_at"), 40) if isinstance(d, dict) else "")
        for eco, d in sorted((data or {}).items())[:5]
        if isinstance(data, dict)
    )
    extra_info = (
        ("lockfiles", lockfiles),
        (
            "packages_checked",
            doc.get("packages_checked") if isinstance(doc.get("packages_checked"), int) else None,
        ),  # fmt: skip
        ("advisory_data_fetched_at", dict(info)),
    )
    return ParsedScan(TOOL, tuple(findings), errors, truncated, LIMITATIONS, extra=extra_info)
