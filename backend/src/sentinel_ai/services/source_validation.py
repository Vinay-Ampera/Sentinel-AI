"""Validation of Git and URL source descriptors. Pure functions: nothing here opens a
network connection, resolves DNS, or runs git. Registration only records a descriptor;
anything that would contact the target needs Stage 6 target authorization and the Stage 8
sandbox, which re-validate (including DNS resolution) at use time.
"""

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import SplitResult, urlsplit

MAX_URL_LENGTH = 2048
BLOCKED_HOSTNAMES = frozenset(
    {"localhost", "metadata.google.internal", "metadata", "instance-data", "kubernetes.default"}
)
BLOCKED_SUFFIXES = (
    ".localhost",
    ".local",
    ".internal",
    ".lan",
    ".home",
    ".corp",
    ".svc",
    ".cluster.local",
)
_HOST_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]", "::1"})


class SourceRejected(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ValidatedUrl:
    url: str
    host: str


def _split(raw: str, schemes: tuple[str, ...]) -> SplitResult:
    if not raw or len(raw) > MAX_URL_LENGTH or raw != raw.strip():
        raise SourceRejected("invalid_url", "URL is empty, too long, or has surrounding whitespace")
    if any(ord(c) <= 32 or ord(c) == 127 for c in raw) or "\\" in raw:
        raise SourceRejected(
            "invalid_url", "URL contains whitespace, control, or backslash characters"
        )
    if not raw.lower().startswith(tuple(f"{scheme}://" for scheme in schemes)):
        allowed = " or ".join(f"{scheme}://" for scheme in schemes)
        raise SourceRejected("unsupported_scheme", f"URL must start with {allowed}")
    try:
        parts = urlsplit(raw)
        parts.port  # noqa: B018 - raises ValueError on a malformed/out-of-range port
    except ValueError:
        raise SourceRejected("invalid_url", "URL is malformed") from None
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise SourceRejected("credentials_in_url", "URLs must not contain credentials")
    if not parts.hostname:
        raise SourceRejected("invalid_url", "URL has no host")
    return parts


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def _check_public_host(host: str) -> None:
    """Reject IP literals that are not public, and internal-looking names."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not _is_public_ip(ip):
            raise SourceRejected("blocked_host", "Host is not a publicly routable address")
        return
    if re.fullmatch(r"[0-9.]+|0x[0-9a-f]+|[0-9]+", host):  # decimal/hex/short IPv4 tricks
        raise SourceRejected("blocked_host", "Ambiguous numeric host is not allowed")
    name = host.rstrip(".")
    if name in BLOCKED_HOSTNAMES or name.endswith(BLOCKED_SUFFIXES) or "." not in name:
        raise SourceRejected("blocked_host", "Host is an internal or single-label name")
    if not all(_HOST_LABEL.match(label) for label in name.split(".")):
        raise SourceRejected("invalid_url", "Host name is not valid")


def require_public_host(host: str) -> None:
    """Public, DNS-named hosts only (raises ``SourceRejected``); for re-checks at use time."""
    _check_public_host(host)


def is_global_address(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return _is_public_ip(ip)


def validate_git_url(raw: str) -> ValidatedUrl:
    """Public HTTPS Git URLs only: no credentials, no SSH/git/file schemes, no query."""
    parts = _split(raw, ("https",))
    if parts.query or parts.fragment:
        raise SourceRejected("invalid_url", "Git URLs must not have a query or fragment")
    if parts.port not in (None, 443):
        raise SourceRejected("blocked_port", "Git URLs must use the default HTTPS port")
    host = (parts.hostname or "").lower()
    _check_public_host(host)
    if len(parts.path.strip("/")) == 0 or ".." in parts.path.split("/"):
        raise SourceRejected("invalid_url", "Git URL must point at a repository path")
    return ValidatedUrl(f"https://{host}{parts.path}", host)


def validate_git_ref(ref: str | None) -> str | None:
    """Branch/tag names that can never be read as an option or revision expression."""
    if ref is None or ref == "":
        return None
    if (
        not _REF.match(ref)
        or ".." in ref
        or "//" in ref
        or ref.endswith(("/", ".", ".lock"))
        or "/." in ref
    ):
        raise SourceRejected("invalid_ref", "Git ref is not a plain branch or tag name")
    return ref


def validate_localhost_url(raw: str) -> ValidatedUrl:
    """http(s) URLs whose host is exactly localhost / 127.0.0.1 / [::1] (matches the
    ``project_sources_shape`` CHECK). Reachability from a sandbox is Q26 / Stage 8."""
    parts = _split(raw, ("http", "https"))
    host = (parts.hostname or "").lower()
    if host not in _LOCAL_HOSTS:
        raise SourceRejected("not_localhost", "Host must be localhost, 127.0.0.1, or [::1]")
    if parts.fragment:
        raise SourceRejected("invalid_url", "URL must not have a fragment")
    return ValidatedUrl(raw, host)


def validate_remote_url(raw: str, environment: str) -> ValidatedUrl:
    """Public http(s) URL of a development or staging deployment. Production is refused:
    production testing is blocked by default and needs Super Admin authorization (Stage 6)."""
    if environment == "production":
        raise SourceRejected(
            "production_blocked",
            "Production targets cannot be registered: production testing is blocked by default",
        )
    if environment not in ("development", "staging"):
        raise SourceRejected("invalid_environment", "environment must be development or staging")
    parts = _split(raw, ("http", "https"))
    if parts.fragment:
        raise SourceRejected("invalid_url", "URL must not have a fragment")
    port = parts.port
    if port is not None and not (1 <= port <= 65535):
        raise SourceRejected("blocked_port", "Port out of range")
    host = (parts.hostname or "").lower()
    _check_public_host(host)
    return ValidatedUrl(raw, host)
