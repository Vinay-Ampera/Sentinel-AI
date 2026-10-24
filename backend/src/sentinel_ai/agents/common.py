"""Shared pieces of the narrow reasoning agents (Stage 11)."""

import re
from collections.abc import Iterable
from typing import Annotated

from pydantic import StringConstraints

# An evidence id as the model must cite it: "<kind>:<token>", platform-generated.
EVIDENCE_ID_PATTERN = r"^[a-z][a-z0-9_]{0,20}:[A-Za-z0-9_.-]{1,60}$"
EvidenceId = Annotated[str, StringConstraints(pattern=EVIDENCE_ID_PATTERN, max_length=90)]

_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


def token(text: str) -> str:
    """Make arbitrary platform text usable as the token part of an evidence id."""
    return _SAFE.sub("_", text)[:60] or "x"


def cites_only(ids: Iterable[str], allowed: set[str]) -> bool:
    """True when every cited id was in the evidence the model was shown (and at least one)."""
    cited = list(ids)
    return bool(cited) and all(i in allowed for i in cited)


def one_line(text: str, limit: int) -> str:
    """Model prose shown to people: collapse whitespace, drop control characters, cap length."""
    cleaned = "".join(ch if ch.isprintable() or ch in "\n\t" else " " for ch in text)
    return " ".join(cleaned.split())[:limit]
