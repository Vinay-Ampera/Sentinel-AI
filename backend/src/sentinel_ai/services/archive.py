"""ZIP validation. Archives are never extracted to disk: entries are only inspected
(headers) and a few small manifest files are read through bounded in-memory reads.
Anything suspicious rejects the whole archive with a stable error code."""

import stat
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06")
ALLOWED_COMPRESSION = (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
MAX_NAME_BYTES = 255
MAX_PATH_CHARS = 512
MAX_DEPTH = 32
RATIO_CHECK_MIN_BYTES = 1024 * 1024  # entries smaller than this cannot be a useful bomb
MAX_COMPRESSION_RATIO = 200


class ArchiveRejected(Exception):
    """The upload is not acceptable. ``code`` is stable; ``message`` is safe to show and
    never echoes attacker-controlled names."""

    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class ArchiveLimits:
    max_upload_bytes: int
    max_uncompressed_bytes: int
    max_files: int


@dataclass(frozen=True)
class ArchiveEntry:
    name: str
    size: int
    compressed_size: int
    is_dir: bool


def has_zip_magic(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(4) in ZIP_MAGICS


def _check_name(name: str) -> None:
    if not name or len(name) > MAX_PATH_CHARS or len(name.encode("utf-8", "replace")) > 1024:
        raise ArchiveRejected("unsafe_path", "Archive contains an invalid entry name")
    if "\\" in name or name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        raise ArchiveRejected("unsafe_path", "Archive contains an absolute or non-portable path")
    for char in name:
        if ord(char) < 32 or ord(char) == 127 or unicodedata.category(char) in ("Cf", "Cs", "Co"):
            raise ArchiveRejected("unsafe_path", "Archive contains control characters in a name")
    parts = name.rstrip("/").split("/")
    if len(parts) > MAX_DEPTH:
        raise ArchiveRejected("unsafe_path", "Archive paths are nested too deeply")
    for part in parts:
        if part in ("", ".", "..") or len(part.encode("utf-8", "replace")) > MAX_NAME_BYTES:
            raise ArchiveRejected("unsafe_path", "Archive contains a path traversal or bad segment")


def inspect_archive(zf: zipfile.ZipFile, limits: ArchiveLimits) -> list[ArchiveEntry]:
    """Validate every entry header and return the entry list (sorted by name).

    Rejects: path traversal/absolute/backslash/control-character names, symlinks and
    special files, encrypted or exotically compressed entries, duplicate (case-folded)
    names, too many files, too much declared uncompressed data, and extreme compression
    ratios. Declared sizes are not trusted for reads: reads are bounded separately.
    """
    infos = zf.infolist()
    if len(infos) > limits.max_files:
        raise ArchiveRejected("too_many_files", "Archive contains too many entries", 413)
    seen: set[str] = set()
    total = 0
    entries: list[ArchiveEntry] = []
    for info in infos:
        _check_name(info.filename)
        folded = unicodedata.normalize("NFC", info.filename).casefold().rstrip("/")
        if folded in seen:
            raise ArchiveRejected("duplicate_entry", "Archive contains duplicate entry names")
        seen.add(folded)
        if info.flag_bits & 0x1:
            raise ArchiveRejected("encrypted_entry", "Encrypted archives are not supported")
        if info.compress_type not in ALLOWED_COMPRESSION:
            raise ArchiveRejected("unsupported_compression", "Unsupported compression method")
        if info.create_system == 3:  # Unix: mode lives in the high 16 bits
            # Many writers (including Python's zipfile) store permission bits only, with
            # no file-type bits; only an explicit non-regular, non-directory type is bad.
            kind = stat.S_IFMT(info.external_attr >> 16)
            if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ArchiveRejected("special_file", "Archive contains links or special files")
        is_dir = info.is_dir()
        if is_dir and info.file_size:
            raise ArchiveRejected("invalid_archive", "Archive is malformed")
        total += info.file_size
        if total > limits.max_uncompressed_bytes:
            raise ArchiveRejected("uncompressed_too_large", "Archive expands beyond the limit", 413)
        if info.file_size >= RATIO_CHECK_MIN_BYTES and info.file_size > MAX_COMPRESSION_RATIO * max(
            info.compress_size, 1
        ):
            raise ArchiveRejected("compression_bomb", "Archive has an excessive compression ratio")
        entries.append(ArchiveEntry(info.filename, info.file_size, info.compress_size, is_dir))
    return sorted(entries, key=lambda e: e.name)


def open_archive(handle: BinaryIO | Path) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(handle)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, EOFError, ValueError):
        raise ArchiveRejected("invalid_archive", "File is not a valid ZIP archive") from None


def read_member(zf: zipfile.ZipFile, name: str, cap: int) -> tuple[bytes, bool]:
    """Read at most ``cap`` bytes of a member (decompressed). Returns (data, truncated).
    Corrupt members yield empty data rather than raising."""
    try:
        with zf.open(name) as member:
            data = member.read(cap + 1)
    except (zipfile.BadZipFile, OSError, EOFError, RuntimeError, NotImplementedError):
        return b"", False
    return data[:cap], len(data) > cap
