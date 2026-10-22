import io
import zipfile

import pytest

from sentinel_ai.services.archive import (
    ArchiveLimits,
    ArchiveRejected,
    inspect_archive,
    open_archive,
)
from support import make_zip

LIMITS = ArchiveLimits(max_upload_bytes=10**7, max_uncompressed_bytes=10**7, max_files=50)


def _inspect(data: bytes, limits: ArchiveLimits = LIMITS):  # type: ignore[no-untyped-def]
    with open_archive(io.BytesIO(data)) as zf:
        return inspect_archive(zf, limits)


def _code(data: bytes, limits: ArchiveLimits = LIMITS) -> str:
    with pytest.raises(ArchiveRejected) as err:
        _inspect(data, limits)
    return err.value.code


def _raw_zip(info: zipfile.ZipInfo, content: bytes = b"x") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(info, content)
    return buf.getvalue()


def test_valid_archive_lists_sorted_entries() -> None:
    entries = _inspect(make_zip({"b.py": "1", "a/": "", "a/c.py": "22"}))
    assert [e.name for e in entries] == ["a/", "a/c.py", "b.py"]
    assert entries[0].is_dir and entries[2].size == 1


@pytest.mark.parametrize(
    "name",
    [
        "../evil.py", "a/../../evil.py", "/etc/passwd", "C:/windows/x", "a\\b.py", "a//b.py",
        "./a.py", "a/./b.py", "bad\nname", "a/\u202eb.py", "x" * 300,
        "/".join(["d"] * 40) + "/f",
    ],
)  # fmt: skip
def test_unsafe_paths_are_rejected(name: str) -> None:
    data = _raw_zip(zipfile.ZipInfo(name))
    assert _code(data) == "unsafe_path"


def test_symlink_entries_are_rejected() -> None:
    info = zipfile.ZipInfo("link")
    info.create_system = 3
    info.external_attr = (0o120777) << 16  # S_IFLNK
    assert _code(_raw_zip(info, b"/etc/passwd")) == "special_file"


def test_regular_unix_entries_are_accepted() -> None:
    info = zipfile.ZipInfo("script.sh")
    info.create_system = 3
    info.external_attr = (0o100755) << 16
    assert [e.name for e in _inspect(_raw_zip(info))] == ["script.sh"]


def test_duplicate_and_case_folded_duplicate_names_are_rejected() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("File.py", "a")
        zf.writestr("file.py", "b")
    assert _code(buf.getvalue()) == "duplicate_entry"


def test_encrypted_entries_are_rejected() -> None:
    data = bytearray(make_zip({"secret.txt": "x"}))
    central = data.index(b"PK\x01\x02")
    data[central + 8] |= 0x1  # general-purpose flag bit 0 = encrypted
    assert _code(bytes(data)) == "encrypted_entry"


def test_unsupported_compression_is_rejected() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_BZIP2) as zf:
        zf.writestr("a.txt", "a")
    assert _code(buf.getvalue()) == "unsupported_compression"


def test_file_count_and_uncompressed_size_limits() -> None:
    many = make_zip({f"f{i}.txt": "x" for i in range(6)})
    assert _code(many, ArchiveLimits(10**7, 10**7, max_files=5)) == "too_many_files"
    big = make_zip({"a.bin": b"a" * 600, "b.bin": b"b" * 600})
    assert (
        _code(big, ArchiveLimits(10**7, max_uncompressed_bytes=1000, max_files=10))
        == "uncompressed_too_large"
    )


def test_compression_bomb_is_rejected_without_decompressing() -> None:
    bomb = make_zip({"zeros.bin": b"\0" * (4 * 1024 * 1024)})
    assert len(bomb) < 20_000
    assert _code(bomb) == "compression_bomb"


def test_garbage_and_truncated_data_are_invalid_archives() -> None:
    for data in (b"", b"not a zip at all", make_zip({"a": "b"})[:20]):
        with pytest.raises(ArchiveRejected) as err:
            open_archive(io.BytesIO(data)).close()
        assert err.value.code == "invalid_archive"


def test_rejection_messages_do_not_echo_entry_names() -> None:
    with pytest.raises(ArchiveRejected) as err:
        _inspect(_raw_zip(zipfile.ZipInfo("../very-secret-name")))
    assert "very-secret-name" not in err.value.message
