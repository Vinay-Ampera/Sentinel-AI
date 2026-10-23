"""Offline dependency audit (Stage 10), run inside the sandbox image.

    python -I /opt/sentinel/dep_audit.py

Reads lockfiles under /workspace/src (parsed as data: nothing is imported, installed or
executed) and compares the exact locked versions with the advisory bundle baked into the image
at /opt/sentinel/advisories (built by sandbox/advisories.py from OSV data when the image is
built). There is no network access at run time. The report is written to /tmp/deps.json for the
trusted runner to frame; the host treats it as untrusted data and validates it again.

Standard library plus the vendored ``packaging`` only. Supported: poetry.lock, pinned
requirements*.txt, Pipfile.lock (PyPI) and package-lock.json / npm-shrinkwrap.json (npm).
yarn.lock and pnpm-lock.yaml are reported as unsupported so the scan is marked incomplete.
"""

import json
import os
import re
import sys
import tomllib
from typing import Any

sys.path.insert(0, os.environ.get("SENTINEL_SITE", "/opt/sentinel/site"))

SOURCE_ROOT = os.environ.get("SENTINEL_SOURCE", "/workspace/src")
ADVISORIES = os.environ.get("SENTINEL_ADVISORIES", "/opt/sentinel/advisories")
REPORT = os.environ.get("SENTINEL_DEPS_REPORT", "/tmp/deps.json")
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".tox"}
MAX_DEPTH = 6
MAX_LOCKFILES = 50
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_PACKAGES = 20000
MAX_RESULTS = 2000
UNSUPPORTED = {"yarn.lock", "pnpm-lock.yaml", "Gemfile.lock", "Cargo.lock", "go.sum", "composer.lock"}
_REQ = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*==\s*([A-Za-z0-9][A-Za-z0-9.+!_-]*)")
_SEMVER = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:-([0-9A-Za-z.-]+))?(?:\+.*)?$")
SEVERITIES = {"low", "medium", "high", "critical"}


def norm_name(ecosystem: str, name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower() if ecosystem == "PyPI" else name


# ---- version comparison ---------------------------------------------------------------------


def _semver_key(raw: str) -> tuple[Any, ...] | None:
    m = _SEMVER.match(raw.strip())
    if not m:
        return None
    nums = tuple(int(g or 0) for g in m.groups()[:3])
    pre = m.group(4)
    if pre is None:
        return (*nums, 1, ())  # a release sorts after its pre-releases
    parts = tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split("."))
    return (*nums, 0, parts)


def version_key(ecosystem: str, raw: str) -> Any:
    """A comparable key, or None when the version cannot be parsed (never guessed)."""
    if ecosystem == "PyPI":
        from packaging.version import InvalidVersion, Version

        try:
            return Version(raw)
        except InvalidVersion:
            return None
    return _semver_key(raw)


def in_range(ecosystem: str, version: str, events: list[dict[str, str]]) -> bool | None:
    """OSV range semantics over sorted events; None when something cannot be compared."""
    key = version_key(ecosystem, version)
    if key is None:
        return None
    parsed: list[tuple[Any, str, str]] = []
    for ev in events:
        for kind in ("introduced", "fixed", "last_affected"):
            if kind in ev:
                raw = ev[kind]
                k = version_key(ecosystem, "0") if raw == "0" else version_key(ecosystem, raw)
                if k is None:
                    return None
                parsed.append((k, kind, raw))
    parsed.sort(key=lambda p: (p[0], p[1] != "introduced"))
    affected = False
    for k, kind, _raw in parsed:
        if kind == "introduced" and key >= k:
            affected = True
        elif kind == "fixed" and key >= k:
            affected = False
        elif kind == "last_affected" and key > k:
            affected = False
    return affected


def is_affected(ecosystem: str, version: str, adv: dict[str, Any]) -> bool | None:
    if version in (adv.get("versions") or []):
        return True
    verdicts = [in_range(ecosystem, version, r.get("events", [])) for r in adv.get("ranges", [])]
    if any(v is True for v in verdicts):
        return True
    return None if any(v is None for v in verdicts) else False


# ---- lockfile parsers (data only) -----------------------------------------------------------


def parse_poetry(data: bytes) -> list[tuple[str, str, str]]:
    doc = tomllib.loads(data.decode("utf-8", "replace"))
    return [
        ("PyPI", str(p["name"]), str(p["version"]))
        for p in doc.get("package", [])
        if isinstance(p, dict) and "name" in p and "version" in p
    ]


def parse_requirements(data: bytes) -> list[tuple[str, str, str]]:
    out = []
    for line in data.decode("utf-8", "replace").splitlines():
        line = line.split(" #")[0].strip().rstrip("\\").strip()
        if not line or line.startswith(("#", "-")):
            continue
        m = _REQ.match(line)
        if m:
            out.append(("PyPI", m.group(1), m.group(2)))
    return out


def parse_pipfile_lock(data: bytes) -> list[tuple[str, str, str]]:
    doc = json.loads(data)
    out = []
    for section in ("default", "develop"):
        for name, meta in (doc.get(section) or {}).items():
            ver = meta.get("version", "") if isinstance(meta, dict) else ""
            if isinstance(ver, str) and ver.startswith("=="):
                out.append(("PyPI", name, ver[2:]))
    return out


def parse_npm_lock(data: bytes) -> list[tuple[str, str, str]]:
    doc = json.loads(data)
    out: list[tuple[str, str, str]] = []
    pkgs = doc.get("packages")
    if isinstance(pkgs, dict):
        for path, meta in pkgs.items():
            if not path or not isinstance(meta, dict) or meta.get("link"):
                continue
            name = meta.get("name") or path.rsplit("node_modules/", 1)[-1]
            if isinstance(meta.get("version"), str):
                out.append(("npm", name, meta["version"]))
        return out

    def walk(deps: dict[str, Any], depth: int = 0) -> None:
        if depth > 32:
            return
        for name, meta in deps.items():
            if isinstance(meta, dict):
                if isinstance(meta.get("version"), str):
                    out.append(("npm", name, meta["version"]))
                if isinstance(meta.get("dependencies"), dict):
                    walk(meta["dependencies"], depth + 1)

    if isinstance(doc.get("dependencies"), dict):
        walk(doc["dependencies"])
    return out


def parser_for(filename: str) -> Any:
    if filename == "poetry.lock":
        return parse_poetry
    if filename == "Pipfile.lock":
        return parse_pipfile_lock
    if filename in ("package-lock.json", "npm-shrinkwrap.json"):
        return parse_npm_lock
    if re.fullmatch(r"requirements[A-Za-z0-9._-]*\.txt", filename):
        return parse_requirements
    return None


def find_lockfiles(root: str) -> tuple[list[str], list[str]]:
    found: list[str] = []
    unsupported: list[str] = []
    base_depth = root.rstrip("/").count("/")
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        if dirpath.count("/") - base_depth >= MAX_DEPTH:
            dirnames[:] = []
        for fn in sorted(filenames):
            rel = os.path.relpath(os.path.join(dirpath, fn), root)
            if fn in UNSUPPORTED:
                unsupported.append(rel)
            elif parser_for(fn) is not None and len(found) < MAX_LOCKFILES:
                found.append(rel)
    return found, unsupported


# ---- advisories -----------------------------------------------------------------------------


def load_advisories(directory: str) -> dict[str, dict[str, Any]]:
    bundles: dict[str, dict[str, Any]] = {}
    for eco, fn in (("PyPI", "pypi.json"), ("npm", "npm.json")):
        path = os.path.join(directory, fn)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        if isinstance(doc, dict) and doc.get("schema") == 1 and doc.get("ecosystem") == eco:
            bundles[eco] = doc
    return bundles


def audit(
    root: str, bundles: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    lockfiles, unsupported = find_lockfiles(root)
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    checked = 0
    for rel in lockfiles:
        full = os.path.join(root, rel)
        try:
            if os.path.islink(full) or os.path.getsize(full) > MAX_FILE_BYTES:
                raise ValueError("unreadable or too large")
            with open(full, "rb") as fh:
                packages = parser_for(os.path.basename(rel))(fh.read())
        except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError) as exc:
            errors.append(f"{rel}: could not be parsed ({type(exc).__name__})")
            continue
        for eco, name, version in packages[: MAX_PACKAGES - checked]:
            checked += 1
            bundle = bundles.get(eco)
            if bundle is None:
                continue
            for adv in bundle.get("packages", {}).get(norm_name(eco, name), []):
                verdict = is_affected(eco, version, adv)
                if verdict is None:
                    errors.append(f"{rel}: {name} {version[:40]}: version could not be compared")
                    continue
                key = (rel, eco, name, version, adv["id"])
                if verdict and key not in seen and len(results) < MAX_RESULTS:
                    seen.add(key)
                    results.append(
                        {
                            "ecosystem": eco, "package": name, "version": version,
                            "lockfile": rel, "advisory_id": adv["id"],
                            "aliases": adv.get("aliases", []), "summary": adv.get("summary", ""),
                            "severity": adv.get("severity", "medium"),
                            "fixed": adv.get("fixed", []), "cwes": adv.get("cwes", []),
                        }
                    )  # fmt: skip
    return {
        "tool": "dependency_audit",
        "advisory_data": {
            eco: {
                "fetched_at": b.get("fetched_at"),
                "source": b.get("source"),
                "advisories": b.get("advisory_count"),
            }
            for eco, b in bundles.items()
        },
        "lockfiles": lockfiles,
        "unsupported_lockfiles": unsupported,
        "packages_checked": checked,
        "results": results,
        "errors": errors[:50],
    }  # fmt: skip


def main() -> int:
    try:
        bundles = load_advisories(ADVISORIES)
    except (OSError, ValueError):
        bundles = {}
    if not bundles:
        print("dependency audit: no advisory data in this image", file=sys.stderr)
        return 3
    report = audit(SOURCE_ROOT, bundles)
    with open(REPORT, "w", encoding="utf-8") as fh:
        json.dump(report, fh)
    print(
        f"dependency audit: {report['packages_checked']} locked packages, "
        f"{len(report['results'])} advisories matched"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
