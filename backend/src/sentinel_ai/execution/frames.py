"""The result frame the in-image runner prints at the very end of stdout (Stage 9).

    @@SENTINEL-RESULT <nonce> <length> <sha256>
    <base64 lines>
    @@SENTINEL-END <nonce>

The host asks for the *last* complete frame carrying the nonce it generated for this run and
checks length and hash. The content is still untrusted (the project's own code wrote the
file), so this only prevents truncation and accidental confusion, not lying about its own
tests. Frames are removed from the stored stdout log.
"""

import base64
import binascii
import hashlib
import re

MARK = b"@@SENTINEL-RESULT "
END = b"@@SENTINEL-END "
_ANY_FRAME = re.compile(
    rb"\n?@@SENTINEL-RESULT [^\n]*\n.*?(?:@@SENTINEL-END [0-9a-zA-Z]*\n?|\Z)", re.S
)


def extract(tail: bytes, nonce: str, max_bytes: int) -> bytes | None:
    """The framed bytes, or None when absent, truncated, oversized or failing its hash."""
    needle = MARK + nonce.encode() + b" "
    start = tail.rfind(needle)
    if start < 0:
        return None
    header_end = tail.find(b"\n", start)
    if header_end < 0:
        return None
    parts = tail[start:header_end].split(b" ")
    if len(parts) != 4:
        return None
    try:
        length = int(parts[2])
    except ValueError:
        return None
    if not 0 <= length <= max_bytes or len(parts[3]) != 64:
        return None
    end_marker = END + nonce.encode()
    end = tail.find(end_marker, header_end)
    if end < 0:
        return None
    try:
        data = base64.b64decode(b"".join(tail[header_end + 1 : end].split()), validate=True)
    except (binascii.Error, ValueError):
        return None
    if len(data) != length or hashlib.sha256(data).hexdigest().encode() != parts[3]:
        return None
    return data


def strip(data: bytes) -> bytes:
    """Remove every frame (genuine, forged or cut off by the output cap) from a log."""
    return _ANY_FRAME.sub(b"\n", data)
