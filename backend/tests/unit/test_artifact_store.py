import uuid
from pathlib import Path

import pytest

from sentinel_ai.services.artifact_store import ArtifactStore, sha256_file


def test_generated_keys_stay_inside_the_root(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    key = store.new_upload_key(uuid.uuid4())
    assert store.path_for(key).is_relative_to(tmp_path.resolve())


@pytest.mark.parametrize("key", ["../outside.zip", "a/../../outside.zip", "/etc/passwd", "", "."])
def test_keys_escaping_the_root_are_refused(tmp_path: Path, key: str) -> None:
    with pytest.raises(ValueError):
        ArtifactStore(tmp_path).path_for(key)


def test_symlink_escape_is_refused(tmp_path: Path) -> None:
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "link").symlink_to(outside)
    with pytest.raises(ValueError):
        ArtifactStore(root).path_for("link/file.zip")


def test_commit_moves_file_and_hashes(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    temp = store.temp_dir() / "t"
    temp.write_bytes(b"abc")
    store.commit(temp, "projects/p/uploads/x.zip")
    final = store.path_for("projects/p/uploads/x.zip")
    assert final.read_bytes() == b"abc" and not temp.exists()
    assert sha256_file(final) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    store.remove("projects/p/uploads/x.zip")
    assert not final.exists()


def test_purge_stale_temp_removes_only_old_regular_files(tmp_path: Path) -> None:
    import os
    import time

    store = ArtifactStore(tmp_path)
    assert store.purge_stale_temp() == 0  # no tmp dir yet
    old, fresh = store.temp_dir() / "old", store.temp_dir() / "fresh"
    old.write_bytes(b"x")
    fresh.write_bytes(b"y")
    os.utime(old, (time.time() - 7200, time.time() - 7200))
    assert store.purge_stale_temp(3600) == 1
    assert fresh.exists() and not old.exists()
