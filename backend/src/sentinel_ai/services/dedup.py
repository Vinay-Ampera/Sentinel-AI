"""Cross-scanner duplicate grouping (Stage 10).

Different tools (and different advisory databases) often report one underlying issue. This
module links such findings through ``finding_groups`` WITHOUT merging, hiding or rewriting
them: each finding keeps its own tool, rule, evidence, status and verification state, so the
original scanner output is never lost and a person can still triage them separately. The
grouping is derived data, recomputed deterministically after every scan, and it never changes a
status.

Two rules, deliberately conservative (a wrong merge hides work; a missed one only costs a click):
  * ``location``: findings on the same source file with the same CWE whose lines are within
    ``LINE_WINDOW`` of a neighbour in the chain, reported by at least two different tools.
  * ``advisory``: findings for the same component (package@version) that share an advisory
    alias (for example a GHSA and a PYSEC record that both name CVE-2024-1234).
Dynamic (ZAP) findings are not grouped with static ones: a URL and a source line are not the
same place, and matching them on a CWE alone would be a guess.
"""

import hashlib
import uuid
from collections import defaultdict

from sqlalchemy.orm import Session

from sentinel_ai.repositories import findings as repo
from sentinel_ai.repositories.findings import GroupCandidate

LINE_WINDOW = 3


def _digest(kind: str, fingerprints: list[str]) -> str:
    """Stable while the smallest member stays (the key must not churn as members come and go)."""
    return f"{kind}:{hashlib.sha256(min(fingerprints).encode()).hexdigest()[:40]}"


class _Sets:
    def __init__(self) -> None:
        self.parent: dict[uuid.UUID, uuid.UUID] = {}

    def find(self, x: uuid.UUID) -> uuid.UUID:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: uuid.UUID, b: uuid.UUID) -> None:
        self.parent[self.find(a)] = self.find(b)


def compute(candidates: list[GroupCandidate]) -> list[tuple[str, str, list[uuid.UUID]]]:
    """(kind, key, member ids) for every group of two or more findings. Pure."""
    out: list[tuple[str, str, list[uuid.UUID]]] = []
    by_id = {c.id: c for c in candidates}

    # advisory: same component sharing an alias
    sets = _Sets()
    owner: dict[tuple[str, str], uuid.UUID] = {}
    for c in candidates:
        if c.category != "dependency" or not c.component:
            continue
        for alias in {*c.aliases}:
            key = (c.component, alias)
            if key in owner:
                sets.union(owner[key], c.id)
            else:
                owner[key] = c.id
    clusters: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for member in {m for m in sets.parent}:
        clusters[sets.find(member)].append(member)
    for members in clusters.values():
        if len(members) >= 2:
            fps = [by_id[m].fingerprint for m in members]
            out.append(("advisory", _digest("advisory", fps), sorted(members)))

    # location: same file + CWE, nearby lines, at least two tools
    buckets: dict[tuple[uuid.UUID | None, str, int], list[GroupCandidate]] = defaultdict(list)
    for c in candidates:
        if c.category == "static_analysis" and c.cwe and c.file_path and c.line_number:
            buckets[(c.source_id, c.file_path, c.cwe)].append(c)
    for bucket in buckets.values():
        bucket.sort(key=lambda c: (c.line_number or 0, c.detected_by, str(c.id)))
        chains: list[list[GroupCandidate]] = []
        for c in bucket:
            gap = (c.line_number or 0) - (chains[-1][-1].line_number or 0) if chains else None
            if gap is None or gap > LINE_WINDOW:
                chains.append([])
            chains[-1].append(c)
        for chain in chains:
            if len({m.detected_by for m in chain}) >= 2:
                fps = [m.fingerprint for m in chain]
                out.append(("location", _digest("location", fps), sorted(m.id for m in chain)))
    return out


def regroup(db: Session, project_id: uuid.UUID) -> int:
    """Recompute the project's groups; returns how many exist afterwards. The caller commits."""
    candidates = repo.group_candidates(db, project_id)
    wanted = compute(candidates)
    in_group: set[uuid.UUID] = set()
    for kind, key, members in wanted:
        gid = repo.upsert_group(db, project_id, key, kind)
        repo.set_group(db, members, gid)
        in_group.update(members)
    loose = [c.id for c in candidates if c.group_id is not None and c.id not in in_group]
    if loose:
        repo.set_group(db, loose, None)
    repo.delete_empty_groups(db, project_id)
    return len(wanted)
