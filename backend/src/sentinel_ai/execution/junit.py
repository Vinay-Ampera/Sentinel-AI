"""Parsing a runner's JUnit XML into normalized cases (Stage 9).

The XML was written by the project's own code, so it is untrusted: size-capped, DOCTYPE and
ENTITY declarations are refused (no entity expansion), text is stripped of control characters
and clipped, counts are bounded, and the parser never fetches anything.
"""

import math
import re
import xml.etree.ElementTree as ET  # noqa: S405 - input is capped and DOCTYPE/ENTITY are refused first
from collections import Counter
from dataclasses import dataclass

from sentinel_ai.execution.interface import CaseResult

MAX_XML_BYTES = 2 * 1024 * 1024
MAX_CASES = 5000
MAX_NAME = 500
MAX_MESSAGE = 1000
MAX_DETAIL = 6000
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_FORBIDDEN = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.I)
_ILLEGAL_BYTES = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]")  # not allowed in XML 1.0


@dataclass(frozen=True)
class ParsedReport:
    cases: tuple[CaseResult, ...]
    truncated: bool  # more cases than MAX_CASES were reported

    def counts(self) -> dict[str, int]:
        return dict(Counter(c.status for c in self.cases))


class InvalidReport(ValueError):
    """The result file is not usable (safe to show)."""


def _clip(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    clean = _CONTROL.sub("", text).strip()
    return clean[:limit] if clean else None


def _millis(raw: str | None) -> int | None:
    try:
        value = float(raw) if raw is not None else None
    except ValueError:
        return None
    if value is None or not math.isfinite(value) or value < 0:  # NaN, infinite or negative
        return None
    return min(int(value * 1000), 10**9)


def parse(xml: bytes) -> ParsedReport:
    if len(xml) > MAX_XML_BYTES:
        raise InvalidReport("the result file is too large")
    if _FORBIDDEN.search(xml):
        raise InvalidReport("the result file contains a DOCTYPE or ENTITY declaration")
    xml = _ILLEGAL_BYTES.sub(b"", xml)  # a stray control byte must not discard every case
    try:
        root = ET.fromstring(xml)  # noqa: S314 - see module docstring
    except ET.ParseError:
        raise InvalidReport("the result file is not valid XML") from None
    if root.tag == "testsuite":
        suites = [root]
    elif root.tag == "testsuites":
        suites = list(root.iter("testsuite"))
    else:
        raise InvalidReport("the result file is not a JUnit report")
    cases: list[CaseResult] = []
    truncated = False
    for suite in suites:
        for case in suite.findall("testcase"):
            if len(cases) >= MAX_CASES:
                truncated = True
                break
            status, message, detail = "passed", None, None
            for tag, mapped in (("error", "error"), ("failure", "failed"), ("skipped", "skipped")):
                node = case.find(tag)
                if node is not None:
                    status = mapped
                    message = _clip(node.get("message"), MAX_MESSAGE)
                    detail = _clip(node.text, MAX_DETAIL)
                    break
            name = _clip(case.get("name"), MAX_NAME) or "(unnamed)"
            cases.append(
                CaseResult(
                    name=name,
                    status=status,
                    suite=_clip(suite.get("name"), MAX_NAME),
                    classname=_clip(case.get("classname"), MAX_NAME),
                    duration_ms=_millis(case.get("time")),
                    message=message,
                    detail=detail,
                )
            )
        if truncated:
            break
    return ParsedReport(tuple(cases), truncated)
