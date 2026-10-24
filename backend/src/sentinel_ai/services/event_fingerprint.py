"""Deterministic normalization and fingerprints for application events (ADR-0011, ``fp-v1``).

The fingerprint decides which events count as "the same error". It must be stable across
requests, processes and deploys, so it uses only the event's own redacted text and fixed rules:
volatile parts (ids, numbers, quoted strings, addresses, absolute path prefixes) become
placeholders and stack frames keep ``file:function`` only (no line numbers). Changing any rule
means a new ``VERSION``; existing groups keep the version they were created with and are never
silently regrouped. Quality of the grouping on real data is unmeasured (Q130).
"""

import hashlib
import re
import uuid

VERSION = "fp-v1"
MAX_MESSAGE_NORM = 512
TOP_FRAMES = 3

_UUID = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_HEX = re.compile(r"\b(?:0x)?[0-9a-fA-F]{8,}\b")
_IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b")
_QUOTED = re.compile(r"""(["'])(?:(?!\1).){1,200}\1""")
_NUMBER = re.compile(r"(?<![A-Za-z_])-?\d+(?:\.\d+)?")
_PATH_PREFIX = re.compile(r"(?:[A-Za-z]:)?(?:/[^\s/:'\"]+){2,}/")
_SPACES = re.compile(r"\s+")
# "File "/app/x.py", line 12, in handler" (Python), "at handler (/app/x.js:12:5)" (Node/Java-ish)
_PY_FRAME = re.compile(r'File "([^"]+)", line \d+, in (\S+)')
_JS_FRAME = re.compile(r"\bat\s+(?:async\s+)?([^\s(]+)\s+\(([^):]+):\d+(?::\d+)?\)")
_JS_BARE_FRAME = re.compile(r"\bat\s+([^\s(]+):\d+(?::\d+)?\s*$", re.M)


def normalize_message(message: str) -> str:
    text = _UUID.sub("<uuid>", message)
    text = _IPV4.sub("<ip>", text)
    text = _QUOTED.sub("<str>", text)
    text = _HEX.sub("<hex>", text)
    text = _PATH_PREFIX.sub("<path>/", text)
    text = _NUMBER.sub("<n>", text)
    return _SPACES.sub(" ", text).strip()[:MAX_MESSAGE_NORM]


def _base(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def top_frames(stack: str | None, limit: int = TOP_FRAMES) -> list[str]:
    """First ``limit`` frames as ``file:function``. Python tracebacks list the innermost call
    last, so they are read from the end; other formats list it first."""
    if not stack:
        return []
    py = [f"{_base(f)}:{fn}" for f, fn in _PY_FRAME.findall(stack)]
    if py:
        return list(reversed(py))[:limit]
    js = [f"{_base(f)}:{fn}" for fn, f in _JS_FRAME.findall(stack)]
    js += [f"{_base(f)}:?" for f in _JS_BARE_FRAME.findall(stack)]
    return js[:limit]


def fingerprint(
    project_id: uuid.UUID,
    *,
    service: str,
    environment: str,
    level_class: str,
    error_type: str | None,
    message: str,
    stack: str | None,
) -> tuple[str, str]:
    """(sha256 hex, normalized message)."""
    norm = normalize_message(message)
    parts = (
        VERSION, str(project_id), service, environment, level_class, error_type or "", norm,
        "|".join(top_frames(stack)),
    )  # fmt: skip
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest(), norm


def overflow_fingerprint(project_id: uuid.UUID) -> str:
    return hashlib.sha256(f"{VERSION}\x1foverflow\x1f{project_id}".encode()).hexdigest()


def level_class(level: str) -> str:
    """Rule level class; ``fatal`` is its own class, ``error`` and above-warning map to error."""
    return {"warning": "warning", "error": "error", "fatal": "fatal"}[level]
