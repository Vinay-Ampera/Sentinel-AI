"""Local-filesystem artifact store (``ARTIFACT_STORAGE_BACKEND=local``).

Keys are generated server-side (never from user input) and every resolved path is
verified to stay inside the store root. Uploaded bytes are only ever read back by the
analyzer; they are never executed.
"""

import hashlib
import os
import time
import uuid
from pathlib import Path

CHUNK = 64 * 1024


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def new_upload_key(self, project_id: uuid.UUID) -> str:
        return f"projects/{project_id}/uploads/{uuid.uuid4().hex}.zip"

    def path_for(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise ValueError("storage key escapes the artifact root")
        return path

    def temp_dir(self) -> Path:
        tmp = self.root / "tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        return tmp

    def commit(self, temp_path: Path, key: str) -> None:
        """Move a validated temp file into place (atomic on the same filesystem)."""
        final = self.path_for(key)
        final.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temp_path, final)
        final.chmod(0o640)

    def purge_stale_temp(self, max_age_seconds: float = 3600.0) -> int:
        """Delete abandoned upload temp files (e.g. after a crash). Returns the count."""
        tmp = self.root / "tmp"
        if not tmp.is_dir():
            return 0
        cutoff = time.time() - max_age_seconds
        removed = 0
        for path in tmp.iterdir():
            if path.is_file() and not path.is_symlink() and path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
        return removed

    def remove(self, key: str) -> None:
        self.path_for(key).unlink(missing_ok=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()
