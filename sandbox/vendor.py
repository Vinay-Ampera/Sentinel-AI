"""Copy the locked, pure-Python pytest stack into sandbox/vendor/ for the image build.

Run with the backend virtualenv (`poetry run python ../sandbox/vendor.py`, done by
`make sandbox-image`). The files come from the versions pinned in backend/poetry.lock, so the
image build needs no network. Only pure-Python distributions are accepted; the exact versions
are written to vendor/VERSIONS.json (and printed) so they can be audited.
"""

import importlib.metadata as md
import json
import shutil
import sys
from pathlib import Path

PACKAGES = (
    "pytest", "pluggy", "iniconfig", "packaging", "pygments",
    "bandit", "stevedore", "pyyaml", "rich", "markdown-it-py", "mdurl",
)  # fmt: skip
# Optional C accelerators with a pure-Python fallback; skipped rather than refused.
OPTIONAL_COMPILED = {"pyyaml": "yaml/_yaml"}
# Kept so plugin entry points (Bandit's tests and formatters) can be discovered offline.
KEEP_METADATA = ("METADATA", "entry_points.txt")
DEST = Path(__file__).resolve().parent / "vendor"


def main() -> int:
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir()
    versions: dict[str, str] = {}
    for name in PACKAGES:
        dist = md.distribution(name)
        versions[name] = dist.version
        for f in dist.files or []:
            parts = f.parts
            if parts[0] == ".." or "__pycache__" in parts or parts[0].endswith(".data"):
                continue
            if parts[0].endswith(".dist-info") and f.name not in KEEP_METADATA:
                continue
            if f.suffix in {".so", ".pyd", ".dylib"}:
                if str(f).startswith(OPTIONAL_COMPILED.get(name, "\0")):
                    continue
                print(f"refusing a compiled extension: {f}", file=sys.stderr)
                return 1
            src = Path(str(dist.locate_file(f)))
            if not src.is_file():
                continue
            out = DEST / f
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, out)
    (DEST / "VERSIONS.json").write_text(json.dumps(versions, indent=2, sort_keys=True) + "\n")
    print("vendored:", ", ".join(f"{k}=={v}" for k, v in versions.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
