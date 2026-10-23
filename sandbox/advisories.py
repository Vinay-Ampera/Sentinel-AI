"""Build the offline advisory bundle that is baked into the sandbox image (Stage 10).

This is an OPERATOR step that needs outbound network access; it is never run by the platform,
by a worker or inside a sandbox:

    python sandbox/advisories.py                 # download OSV dumps for PyPI and npm
    python sandbox/advisories.py --from-dir DIR  # use already downloaded <Ecosystem>/all.zip

It writes sandbox/advisories/pypi.json, npm.json and meta.json (compact, normalized, with the
fetch time, source and a SHA-256 of each file). The data is OSV (https://osv.dev), which
republishes the GitHub Advisory Database and PyPA advisories under open licences; check the
licence terms of the feeds you ship. ``make sandbox-image`` then labels the image with the
fetch time so the host can refuse results from stale data without trusting the container.

Only the fields the audit needs are kept, and text is clipped, so the bundle stays small and
nothing from a record is ever executed or rendered as markup.
"""

import argparse
import hashlib
import io
import json
import re
import sys
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FEEDS = {
    "PyPI": ("pypi.json", "https://osv-vulnerabilities.storage.googleapis.com/PyPI/all.zip"),
    "npm": ("npm.json", "https://osv-vulnerabilities.storage.googleapis.com/npm/all.zip"),
}
DEST = Path(__file__).resolve().parent / "advisories"
MAX_DOWNLOAD = 400 * 1024 * 1024
_SEVERITY = {"LOW": "low", "MODERATE": "medium", "MEDIUM": "medium", "HIGH": "high", "CRITICAL": "critical"}
_CWE = re.compile(r"CWE-(\d{1,5})")


def norm_name(ecosystem: str, name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower() if ecosystem == "PyPI" else name


def compact(record: dict[str, Any], ecosystem: str) -> dict[str, list[dict[str, Any]]]:
    """One OSV record -> {normalized package name: [compact advisory]} for this ecosystem."""
    if not isinstance(record, dict) or record.get("withdrawn") or not isinstance(record.get("id"), str):
        return {}
    db = record.get("database_specific") or {}
    severity = _SEVERITY.get(str(db.get("severity", "")).upper(), "medium")
    cwes = sorted(
        {int(m) for c in (db.get("cwe_ids") or []) if isinstance(c, str) for m in _CWE.findall(c)}
    )
    out: dict[str, list[dict[str, Any]]] = {}
    for aff in record.get("affected") or []:
        pkg = aff.get("package") or {}
        if pkg.get("ecosystem") != ecosystem or not isinstance(pkg.get("name"), str):
            continue
        ranges = []
        fixed: list[str] = []
        for rng in aff.get("ranges") or []:
            if rng.get("type") not in ("ECOSYSTEM", "SEMVER"):
                continue  # GIT ranges cannot be matched to a published version
            events = [
                {k: str(v)[:100] for k, v in ev.items() if k in ("introduced", "fixed", "last_affected")}
                for ev in rng.get("events") or []
            ]
            ranges.append({"events": events})
            fixed += [e["fixed"] for e in events if "fixed" in e]
        versions = [str(v)[:100] for v in (aff.get("versions") or [])][:2000]
        if not ranges and not versions:
            continue
        out.setdefault(norm_name(ecosystem, pkg["name"]), []).append(
            {
                "id": record["id"][:60],
                "aliases": [a[:60] for a in (record.get("aliases") or []) if isinstance(a, str)][:10],
                "summary": " ".join(str(record.get("summary") or "").split())[:300],
                "severity": severity,
                "cwes": cwes[:10],
                "ranges": ranges,
                "versions": versions if not ranges else [],
                "fixed": sorted(set(fixed))[:10],
            }
        )
    return out


def build(ecosystem: str, zip_bytes: bytes, source: str) -> dict[str, Any]:
    packages: dict[str, list[dict[str, Any]]] = {}
    count = 0
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for name in zf.namelist():
            if not name.endswith(".json"):
                continue
            try:
                record = json.loads(zf.read(name))
            except ValueError:
                continue
            for pkg, advs in compact(record, ecosystem).items():
                packages.setdefault(pkg, []).extend(advs)
                count += len(advs)
    return {
        "schema": 1,
        "ecosystem": ecosystem,
        "source": source,
        "fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "advisory_count": count,
        "packages": packages,
    }


def _download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as resp:  # noqa: S310 - fixed https URL above
        data = resp.read(MAX_DOWNLOAD + 1)
    if len(data) > MAX_DOWNLOAD:
        raise SystemExit(f"{url}: download is larger than {MAX_DOWNLOAD} bytes")
    return data


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-dir", type=Path, help="directory holding PyPI/all.zip and npm/all.zip")
    args = ap.parse_args()
    DEST.mkdir(exist_ok=True)
    meta: dict[str, Any] = {}
    for eco, (filename, url) in FEEDS.items():
        if args.from_dir:
            data = (args.from_dir / eco / "all.zip").read_bytes()
            source = f"file:{eco}/all.zip"
        else:
            data = _download(url)
            source = url
        doc = build(eco, data, source)
        body = json.dumps(doc, separators=(",", ":"), sort_keys=True).encode()
        (DEST / filename).write_bytes(body)
        meta[eco] = {
            "file": filename, "fetched_at": doc["fetched_at"], "source": source,
            "advisories": doc["advisory_count"], "sha256": hashlib.sha256(body).hexdigest(),
        }  # fmt: skip
        print(f"{eco}: {doc['advisory_count']} advisories, {len(body)} bytes")
    (DEST / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
