"""All SQL for findings, their events, evidence links and verification attempts (Stage 10).

``findings`` rows are unique per ``(project_id, fingerprint)``; a scanner that sees the same
issue again updates the row instead of adding one. ``finding_events`` is append-only, and
the database refuses ``confirmed`` without an evidence row (migration 0002 trigger).
"""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

OPEN_STATUSES = ("new", "triaged", "in_progress", "reopened")
RESOLVED_STATUSES = ("fixed", "verified_fixed")
_FINDING = (
    "id, project_id, first_run_id, last_run_id, result_id, source_id, fingerprint, title, "
    "description, category, detected_by, rule_id, file_path, line_number, severity, confidence, "
    "verification_state, status, limitations, occurrences, assigned_to, resolved_at, created_at, "
    "updated_at, cwe, component, aliases, group_id"
)


@dataclass(frozen=True)
class FindingRecord:
    id: uuid.UUID
    project_id: uuid.UUID
    first_run_id: uuid.UUID | None
    last_run_id: uuid.UUID | None
    result_id: uuid.UUID | None
    source_id: uuid.UUID | None
    fingerprint: str
    title: str
    description: str | None
    category: str
    detected_by: str
    rule_id: str | None
    file_path: str | None
    line_number: int | None
    severity: str
    confidence: str
    verification_state: str
    status: str
    limitations: str | None
    occurrences: int
    assigned_to: uuid.UUID | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime
    cwe: int | None
    component: str | None
    aliases: list[str]
    group_id: uuid.UUID | None


@dataclass(frozen=True)
class FindingEventRecord:
    id: int
    finding_id: uuid.UUID
    event_type: str
    from_value: str | None
    to_value: str | None
    actor_user_id: uuid.UUID | None
    detail: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class FindingEvidenceRecord:
    artifact_id: uuid.UUID
    filename: str | None
    kind: str
    size_bytes: int
    note: str | None
    run_id: uuid.UUID | None


@dataclass(frozen=True)
class AttemptRecord:
    id: uuid.UUID
    finding_id: uuid.UUID
    run_id: uuid.UUID
    outcome: str
    method: str
    notes: str | None
    evidence_artifact_id: uuid.UUID | None
    created_by: uuid.UUID | None
    created_at: datetime


def _finding(row: Any) -> FindingRecord:
    return FindingRecord(*row)


def get_finding(
    db: Session, finding_id: uuid.UUID, *, for_update: bool = False
) -> FindingRecord | None:
    lock = " FOR UPDATE" if for_update else ""
    row = db.execute(
        text(f"SELECT {_FINDING} FROM public.findings WHERE id = :i{lock}"), {"i": finding_id}
    ).one_or_none()
    return _finding(row) if row else None


def list_findings(
    db: Session,
    project_id: uuid.UUID,
    *,
    status: str | None,
    severity: str | None,
    limit: int,
) -> list[FindingRecord]:
    rows = db.execute(
        text(
            f"SELECT {_FINDING} FROM public.findings WHERE project_id = :p "
            "AND (CAST(:s AS text) IS NULL OR status = :s) "
            "AND (CAST(:v AS text) IS NULL OR severity = :v) "
            "ORDER BY array_position(ARRAY['critical','high','medium','low','info'], severity), "
            "created_at DESC, id LIMIT :n"
        ),
        {"p": project_id, "s": status, "v": severity, "n": limit},
    ).all()
    return [_finding(r) for r in rows]


def insert_event(
    db: Session,
    finding_id: uuid.UUID,
    event_type: str,
    *,
    from_value: str | None = None,
    to_value: str | None = None,
    actor_user_id: uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    db.execute(
        text(
            "INSERT INTO public.finding_events (finding_id, event_type, from_value, to_value, "
            "actor_user_id, detail) VALUES (:f, :t, :a, :b, :u, CAST(:d AS jsonb))"
        ),
        {"f": finding_id, "t": event_type, "a": from_value, "b": to_value, "u": actor_user_id,
         "d": json.dumps(detail or {})},
    )  # fmt: skip


def list_events(db: Session, finding_id: uuid.UUID) -> list[FindingEventRecord]:
    rows = db.execute(
        text(
            "SELECT id, finding_id, event_type, from_value, to_value, actor_user_id, detail, "
            "created_at FROM public.finding_events WHERE finding_id = :f ORDER BY id LIMIT 500"
        ),
        {"f": finding_id},
    ).all()
    return [FindingEventRecord(*r) for r in rows]


def insert_finding(
    db: Session,
    *,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    result_id: uuid.UUID,
    source_id: uuid.UUID | None,
    fingerprint: str,
    title: str,
    description: str,
    category: str,
    detected_by: str,
    rule_id: str,
    file_path: str,
    line_number: int | None,
    severity: str,
    confidence: str,
    limitations: str,
    cwe: int | None = None,
    component: str | None = None,
    aliases: tuple[str, ...] = (),
) -> uuid.UUID | None:
    """None when a finding with this fingerprint already exists for the project."""
    row = db.execute(
        text(
            "INSERT INTO public.findings (project_id, first_run_id, last_run_id, result_id, "
            "source_id, fingerprint, title, description, category, detected_by, rule_id, "
            "file_path, line_number, severity, confidence, limitations, cwe, component, aliases) "
            "VALUES (:p, :r, :r, :res, :src, :fp, :t, :d, :c, :by, :rule, :path, :line, :sev, "
            ":conf, :lim, :cwe, :comp, CAST(:al AS text[])) ON CONFLICT (project_id, fingerprint) DO NOTHING RETURNING id"
        ),
        {"p": project_id, "r": run_id, "res": result_id, "src": source_id, "fp": fingerprint,
         "t": title, "d": description, "c": category, "by": detected_by, "rule": rule_id,
         "path": file_path, "line": line_number, "sev": severity, "conf": confidence,
         "lim": limitations, "cwe": cwe, "comp": component, "al": list(aliases)},
    ).one_or_none()  # fmt: skip
    return uuid.UUID(str(row[0])) if row else None


def get_by_fingerprint(
    db: Session, project_id: uuid.UUID, fingerprint: str, *, for_update: bool = False
) -> FindingRecord | None:
    lock = " FOR UPDATE" if for_update else ""
    row = db.execute(
        text(
            f"SELECT {_FINDING} FROM public.findings WHERE project_id = :p "
            f"AND fingerprint = :f{lock}"
        ),
        {"p": project_id, "f": fingerprint},
    ).one_or_none()
    return _finding(row) if row else None


def mark_seen(
    db: Session,
    finding_id: uuid.UUID,
    *,
    run_id: uuid.UUID,
    result_id: uuid.UUID,
    source_id: uuid.UUID | None,
    line_number: int | None,
    severity: str,
    confidence: str,
    reopen: bool,
) -> None:
    db.execute(
        text(
            "UPDATE public.findings SET last_run_id = :r, result_id = :res, "
            "source_id = COALESCE(:src, source_id), line_number = :line, severity = :sev, confidence = :conf, "
            "occurrences = occurrences + 1, updated_at = now(), "
            "status = CASE WHEN :reopen THEN 'reopened' ELSE status END, "
            "resolved_at = CASE WHEN :reopen THEN NULL ELSE resolved_at END WHERE id = :i"
        ),
        {"i": finding_id, "r": run_id, "res": result_id, "src": source_id, "line": line_number,
         "sev": severity,
         "conf": confidence, "reopen": reopen},
    )  # fmt: skip


def link_evidence(
    db: Session, finding_id: uuid.UUID, artifact_id: uuid.UUID, note: str | None
) -> bool:
    row = db.execute(
        text(
            "INSERT INTO public.finding_evidence (finding_id, artifact_id, note) "
            "VALUES (:f, :a, :n) ON CONFLICT DO NOTHING RETURNING 1"
        ),
        {"f": finding_id, "a": artifact_id, "n": note},
    ).one_or_none()
    return row is not None


def list_evidence(db: Session, finding_id: uuid.UUID) -> list[FindingEvidenceRecord]:
    rows = db.execute(
        text(
            "SELECT a.id, a.original_filename, a.kind, a.size_bytes, fe.note, a.run_id "
            "FROM public.finding_evidence fe JOIN public.artifacts a ON a.id = fe.artifact_id "
            "WHERE fe.finding_id = :f AND a.deleted_at IS NULL ORDER BY fe.created_at, a.id"
        ),
        {"f": finding_id},
    ).all()
    return [FindingEvidenceRecord(*r) for r in rows]


def unseen_open_findings(
    db: Session,
    project_id: uuid.UUID,
    source_id: uuid.UUID,
    detected_by: str,
    seen_fingerprints: list[str],
) -> list[FindingRecord]:
    """Unresolved findings of this tool on this source that the latest complete scan did not
    report again (candidates for an automatic re-scan verification)."""
    rows = db.execute(
        text(
            f"SELECT {_FINDING} FROM public.findings WHERE project_id = :p AND source_id = :s "
            "AND detected_by = :by AND status IN ('new','triaged','in_progress','reopened','fixed') "
            "AND NOT (fingerprint = ANY(CAST(:seen AS text[]))) ORDER BY created_at, id FOR UPDATE"
        ),
        {"p": project_id, "s": source_id, "by": detected_by, "seen": seen_fingerprints},
    ).all()
    return [_finding(r) for r in rows]


def transition_status(db: Session, finding_id: uuid.UUID, from_status: str, to_status: str) -> bool:
    row = db.execute(
        text(
            "UPDATE public.findings SET status = :to, updated_at = now(), "
            "resolved_at = CASE WHEN :to IN ('fixed','verified_fixed','accepted_risk',"
            "'false_positive') THEN now() ELSE NULL END "
            "WHERE id = :i AND status = :from RETURNING 1"
        ),
        {"i": finding_id, "from": from_status, "to": to_status},
    ).one_or_none()
    return row is not None


def set_verification_state(db: Session, finding_id: uuid.UUID, state: str) -> None:
    db.execute(
        text(
            "UPDATE public.findings SET verification_state = :s, updated_at = now() WHERE id = :i"
        ),
        {"i": finding_id, "s": state},
    )


def insert_attempt(
    db: Session,
    *,
    finding_id: uuid.UUID,
    run_id: uuid.UUID,
    outcome: str,
    method: str,
    notes: str | None,
    evidence_artifact_id: uuid.UUID | None,
    created_by: uuid.UUID | None,
) -> None:
    db.execute(
        text(
            "INSERT INTO public.verification_attempts (finding_id, run_id, outcome, method, "
            "notes, evidence_artifact_id, created_by) VALUES (:f, :r, :o, :m, :n, :a, :u)"
        ),
        {"f": finding_id, "r": run_id, "o": outcome, "m": method, "n": notes,
         "a": evidence_artifact_id, "u": created_by},
    )  # fmt: skip


def list_attempts(db: Session, finding_id: uuid.UUID) -> list[AttemptRecord]:
    rows = db.execute(
        text(
            "SELECT id, finding_id, run_id, outcome, method, notes, evidence_artifact_id, "
            "created_by, created_at FROM public.verification_attempts WHERE finding_id = :f "
            "ORDER BY created_at, id LIMIT 200"
        ),
        {"f": finding_id},
    ).all()
    return [AttemptRecord(*r) for r in rows]


GROUP_CANDIDATE_LIMIT = 20000


@dataclass(frozen=True)
class GroupCandidate:
    id: uuid.UUID
    detected_by: str
    category: str
    source_id: uuid.UUID | None
    file_path: str | None
    line_number: int | None
    cwe: int | None
    component: str | None
    aliases: list[str]
    fingerprint: str
    group_id: uuid.UUID | None


def group_candidates(db: Session, project_id: uuid.UUID) -> list[GroupCandidate]:
    """Findings that carry something tools can agree on (a CWE or advisory aliases)."""
    rows = db.execute(
        text(
            "SELECT id, detected_by, category, source_id, file_path, line_number, cwe, component, "
            "aliases, fingerprint, group_id FROM public.findings WHERE project_id = :p "
            "AND (cwe IS NOT NULL OR cardinality(aliases) > 0) ORDER BY created_at, id LIMIT :n"
        ),
        {"p": project_id, "n": GROUP_CANDIDATE_LIMIT},
    ).all()
    return [GroupCandidate(*r) for r in rows]


def upsert_group(db: Session, project_id: uuid.UUID, group_key: str, kind: str) -> uuid.UUID:
    row = db.execute(
        text(
            "INSERT INTO public.finding_groups (project_id, group_key, kind) VALUES (:p, :k, :kind) "
            "ON CONFLICT (project_id, group_key) DO UPDATE SET updated_at = now() RETURNING id"
        ),
        {"p": project_id, "k": group_key, "kind": kind},
    ).one()
    return uuid.UUID(str(row[0]))


def set_group(db: Session, finding_ids: list[uuid.UUID], group_id: uuid.UUID | None) -> None:
    db.execute(
        text("UPDATE public.findings SET group_id = :g WHERE id = ANY(CAST(:ids AS uuid[]))"),
        {"g": group_id, "ids": [str(i) for i in finding_ids]},
    )


def delete_empty_groups(db: Session, project_id: uuid.UUID) -> None:
    db.execute(
        text(
            "DELETE FROM public.finding_groups g WHERE g.project_id = :p AND NOT EXISTS "
            "(SELECT 1 FROM public.findings f WHERE f.group_id = g.id)"
        ),
        {"p": project_id},
    )


@dataclass(frozen=True)
class GroupRecord:
    id: uuid.UUID
    project_id: uuid.UUID
    kind: str
    members: list[FindingRecord]


def list_groups(db: Session, project_id: uuid.UUID, limit: int) -> list[GroupRecord]:
    groups = db.execute(
        text(
            "SELECT g.id, g.kind FROM public.finding_groups g WHERE g.project_id = :p "
            "ORDER BY g.updated_at DESC, g.id LIMIT :n"
        ),
        {"p": project_id, "n": limit},
    ).all()
    if not groups:
        return []
    rows = db.execute(
        text(
            f"SELECT {_FINDING} FROM public.findings WHERE project_id = :p "
            "AND group_id = ANY(CAST(:ids AS uuid[])) "
            "ORDER BY array_position(ARRAY['critical','high','medium','low','info'], severity), "
            "detected_by, id"
        ),
        {"p": project_id, "ids": [str(g[0]) for g in groups]},
    ).all()
    by_group: dict[uuid.UUID, list[FindingRecord]] = {}
    for row in rows:
        rec = _finding(row)
        if rec.group_id is not None:
            by_group.setdefault(rec.group_id, []).append(rec)
    return [
        GroupRecord(
            uuid.UUID(str(g[0])), project_id, str(g[1]), by_group.get(uuid.UUID(str(g[0])), [])
        )
        for g in groups
    ]


def group_members(db: Session, group_id: uuid.UUID, project_id: uuid.UUID) -> list[FindingRecord]:
    rows = db.execute(
        text(
            f"SELECT {_FINDING} FROM public.findings WHERE project_id = :p AND group_id = :g "
            "ORDER BY detected_by, id"
        ),
        {"p": project_id, "g": group_id},
    ).all()
    return [_finding(r) for r in rows]


def count_by_status(db: Session, project_id: uuid.UUID) -> dict[str, int]:
    rows = db.execute(
        text("SELECT status, count(*) FROM public.findings WHERE project_id = :p GROUP BY status"),
        {"p": project_id},
    ).all()
    return {str(s): int(n) for s, n in rows}
