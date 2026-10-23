"""Helpers shared by the scanner report parsers (Stage 10).

A scanner's report is untrusted data written by a process that read the project (or probed a
target): every field is type-checked, text has control characters removed and is clipped, and
paths are accepted only when they are plain relative paths.
"""

import hashlib
import re
from typing import Any

TEXT_LIMIT = 500
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SAFE_PATH = re.compile(r"[A-Za-z0-9_@+=,.\- /]{1,400}")
_TAGS = re.compile(r"<[^>]*>")
_ENTITIES = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'", "&nbsp;": " "}


def clean_text(value: Any, limit: int = TEXT_LIMIT) -> str:
    return _CONTROL.sub("", value if isinstance(value, str) else "")[:limit]


def strip_markup(value: Any, limit: int = TEXT_LIMIT) -> str:
    """Plain text from a field that may carry HTML (ZAP descriptions)."""
    text = _TAGS.sub(" ", value if isinstance(value, str) else "")
    for entity, char in _ENTITIES.items():
        text = text.replace(entity, char)
    return " ".join(clean_text(text, limit * 2).split())[:limit]


def safe_path(value: Any) -> str:
    """A plain relative path, or ``(unknown)``; absolute paths, ``..`` and options are refused."""
    if not isinstance(value, str):
        return "(unknown)"
    clean = value[2:] if value.startswith("./") else value
    parts = clean.split("/")
    if (
        not _SAFE_PATH.fullmatch(clean)
        or clean.startswith(("/", "-"))
        or any(p in ("", "..") for p in parts)
    ):
        return "(unknown)"
    return clean


def as_int(value: Any, *, low: int, high: int) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        value = int(value)
    return value if isinstance(value, int) and low <= value <= high else None


def fingerprint(tool: str, *parts: object) -> str:
    """``tool:`` + a stable digest of the identifying parts (never line numbers or snippets)."""
    digest = hashlib.sha256("\0".join([tool, *map(str, parts)]).encode()).hexdigest()
    return f"{tool}:{digest[:40]}"


def cwe_number(value: Any) -> int | None:
    """``CWE-78: ...`` / ``78`` / ``[...]`` -> 78, taking the first usable entry."""
    items = value if isinstance(value, list) else [value]
    for item in items:
        if isinstance(item, int) and not isinstance(item, bool) and 0 < item < 100000:
            return item
        if isinstance(item, str):
            m = re.match(r"\s*(?:CWE-)?(\d{1,5})\b", item, re.I)
            if m and int(m.group(1)) > 0:
                return int(m.group(1))
    return None
