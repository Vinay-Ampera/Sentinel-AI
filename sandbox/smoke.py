"""Sandbox self-check (the `sandbox_smoke` check): describe the extracted source tree.

It lists and counts files only; it never imports, executes or follows anything from the
project. Prints one JSON object and exits 0 when the tree could be read.
"""

import json
import os
import sys

ROOT = os.getcwd()
MAX_ENTRIES = 200_000


def main() -> int:
    files = dirs = total = 0
    by_ext: dict[str, int] = {}
    largest = 0
    for _dirpath, dirnames, filenames in os.walk(ROOT, followlinks=False):
        dirs += len(dirnames)
        for name in filenames:
            files += 1
            if files > MAX_ENTRIES:
                print(json.dumps({"error": "too many files"}))
                return 1
            ext = os.path.splitext(name)[1].lower() or "(none)"
            by_ext[ext] = by_ext.get(ext, 0) + 1
            try:
                size = os.lstat(os.path.join(_dirpath, name)).st_size
            except OSError:
                continue
            total += size
            largest = max(largest, size)
    top = dict(sorted(by_ext.items(), key=lambda kv: (-kv[1], kv[0]))[:10])
    print(
        json.dumps(
            {
                "check": "sandbox_smoke",
                "files": files,
                "directories": dirs,
                "bytes": total,
                "largest_file_bytes": largest,
                "top_extensions": top,
                "uid": os.getuid(),
                "project_code_executed": False,
            },
            sort_keys=True,
        )
    )
    return 0 if files else 2


if __name__ == "__main__":
    sys.exit(main())
