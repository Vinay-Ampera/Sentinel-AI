"""Pattern-based text redaction shared by model prompts (ADR-0010) and stored application
events (ADR-0011), so the two cannot drift apart.

Layers, in order: (1) configured secrets by exact value; (2) credential shapes (``key=value``
and quoted JSON pairs for secret-like names, Authorization/Cookie headers, bearer tokens, URL
credentials, private-key blocks, well-known token formats); (3) e-mail addresses; (4) long
high-entropy tokens no pattern named; (5) control sequences. Each replacement is
``[REDACTED:<kind>]``; the pass is idempotent and reports counts only, never the removed values.
It is a best-effort filter, not proof that no secret remains (Q113).
"""

import math
import re
from collections import Counter
from collections.abc import Iterable

MIN_SECRET_LEN = 6  # same floor as execution/evidence.py


# The full ANSI sequence must be tried before a lone ESC, or its tail ("[31m") would remain.
_CONTROL = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SECRET_NAME = r"(?:pass(?:word|wd)?|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|credential|auth(?:orization)?|session(?:id)?|cookie|csrf)"


def _tag(kind: str) -> str:
    return f"[REDACTED:{kind}]"


# (kind, pattern, replacement). Replacements keep the key so the line stays readable.
_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "private_key",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S),
        _tag("private_key"),
    ),
    (
        "header",
        re.compile(r"(?im)^(\s*(?:authorization|proxy-authorization|cookie|set-cookie|x-api-key|x-auth-token)\s*:)[ \t]*+(?!\[REDACTED:header\]$).+$"),
        r"\1 " + _tag("header"),
    ),
    ("bearer", re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 " + _tag("token")),
    (
        "url_credentials",
        re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@"),
        r"\1" + _tag("credentials") + "@",
    ),
    (
        "json_pair",
        re.compile(rf"""(?ix)(["']?[\w.-]{{0,40}}{_SECRET_NAME}[\w.-]{{0,40}}["']?\s*[:=]\s*)(["'])[^"'\n]*\2"""),
        r"\1" + _tag("secret"),
    ),
    (
        "pair",
        re.compile(rf"(?i)(\b[\w.-]{{0,40}}{_SECRET_NAME}[\w.-]{{0,40}}\s*[=:]\s*)(?!\[REDACTED)[^\s,;\"']+"),
        r"\1" + _tag("secret"),
    ),
    ("google_key", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"), _tag("api_key")),
    ("aws_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), _tag("api_key")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b"), _tag("token")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"), _tag("token")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), _tag("api_key")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), _tag("token")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b"), _tag("email")),
)  # fmt: skip

# Candidate secrets no pattern named: long runs of key-like characters.
_TOKENISH = re.compile(r"(?<![A-Za-z0-9+/_=-])[A-Za-z0-9+/_=-]{32,}(?![A-Za-z0-9+/_=-])")
_HEX = re.compile(r"[0-9a-f]+")
_HASH_LENGTHS = {32, 40, 64}  # md5 / sha1 / sha256 hex: content hashes and commit ids, not secrets
MIN_ENTROPY_BITS = 4.0


def _entropy(text: str) -> float:
    counts = Counter(text)
    return -sum(c / len(text) * math.log2(c / len(text)) for c in counts.values())


def _looks_secret(token: str) -> bool:
    if token.startswith("[REDACTED"):
        return False
    if len(token) in _HASH_LENGTHS and _HEX.fullmatch(token):
        return False
    has_digit = any(c.isdigit() for c in token)
    has_alpha = any(c.isalpha() for c in token)
    return has_digit and has_alpha and _entropy(token) >= MIN_ENTROPY_BITS


def prepare_secrets(secrets: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({s for s in secrets if len(s) >= MIN_SECRET_LEN}, key=len, reverse=True))


def redact_text(text: str, secrets: tuple[str, ...]) -> tuple[str, dict[str, int]]:
    """``secrets`` must come from ``prepare_secrets``."""
    counts: Counter[str] = Counter()
    for secret in secrets:
        n = text.count(secret)
        if n:
            counts["configured_secret"] += n
            text = text.replace(secret, _tag("secret"))
    for kind, pattern, replacement in _PATTERNS:
        text, n = pattern.subn(replacement, text)
        if n:
            counts[kind] += n

    def entropy_sub(match: re.Match[str]) -> str:
        if not _looks_secret(match.group(0)):
            return match.group(0)
        counts["high_entropy"] += 1
        return _tag("token")

    text = _TOKENISH.sub(entropy_sub, text)
    text, n = _CONTROL.subn("", text)
    if n:
        counts["control_chars"] += n
    return text, dict(counts)
