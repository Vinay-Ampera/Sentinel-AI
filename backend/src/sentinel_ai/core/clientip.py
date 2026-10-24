"""Client address behind a reverse proxy (ADR-0002 note, ADR-0011, Q136).

By default (no trusted proxy configured) the client is the direct peer and ``X-Forwarded-For``
is ignored, because anyone can send that header. When the operator lists the proxies in
``TRUSTED_PROXY_CIDRS``, the header is honoured **only for requests that arrive from one of
them**, and the client is the right-most address in the chain that is not itself a trusted
proxy. A malformed entry stops the walk and the direct peer is used, never a guess."""

import ipaddress
from collections.abc import Sequence

Network = ipaddress.IPv4Network | ipaddress.IPv6Network


def parse_networks(cidrs: Sequence[str]) -> tuple[Network, ...]:
    return tuple(ipaddress.ip_network(c.strip(), strict=False) for c in cidrs if c.strip())


def _ip(text: str | None) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address((text or "").strip())
    except ValueError:
        return None


def _trusted(addr: ipaddress.IPv4Address | ipaddress.IPv6Address, nets: Sequence[Network]) -> bool:
    return any(addr.version == n.version and addr in n for n in nets)


def client_ip(
    peer: str | None, forwarded_for: str | None, trusted: Sequence[Network]
) -> str | None:
    """The address to rate-limit and audit. ``None`` when the peer is not an IP address."""
    peer_addr = _ip(peer)
    if peer_addr is None:
        return None
    if not trusted or not forwarded_for or not _trusted(peer_addr, trusted):
        return str(peer_addr)
    for part in reversed(forwarded_for.split(",")):
        addr = _ip(part)
        if addr is None:
            return str(peer_addr)  # malformed: do not guess
        if not _trusted(addr, trusted):
            return str(addr)
    return str(peer_addr)  # every hop is a trusted proxy
