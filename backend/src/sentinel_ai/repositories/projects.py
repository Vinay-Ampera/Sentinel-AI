"""All SQL for projects, memberships, sources, upload artifacts, and analysis snapshots.
Every child lookup takes ``project_id`` so an ID alone never reaches another project."""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class ProjectRecord:
    id: uuid.UUID
    name: str
    description: str | None
    owner_user_id: uuid.UUID
    application_type: str
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class MemberRecord:
    user_id: uuid.UUID
    email: str
    display_name: str
    access_level: str
    created_at: datetime


@dataclass(frozen=True)
class SourceRecord:
    id: uuid.UUID
    project_id: uuid.UUID
    source_type: str
    name: str
    is_active: bool
    upload_artifact_id: uuid.UUID | None
    created_by: uuid.UUID
    created_at: datetime
    size_bytes: int | None
    sha256: str | None
    git_url: str | None
    git_ref: str | None
    target_url: str | None
    environment: str | None


@dataclass(frozen=True)
class ArtifactRecord:
    id: uuid.UUID
    project_id: uuid.UUID
    storage_key: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class SnapshotRecord:
    id: uuid.UUID
    project_id: uuid.UUID
    source_id: uuid.UUID
    content_sha256: str | None
    detected: dict[str, Any]
    status: str
    error_summary: str | None
    created_by: uuid.UUID | None
    created_at: datetime
    completed_at: datetime | None


_PROJECT = "id, name, description, owner_user_id, application_type, status, created_at, updated_at"
_SOURCE_SELECT = (
    "SELECT s.id, s.project_id, s.source_type, s.name, s.is_active, s.upload_artifact_id, "
    "s.created_by, s.created_at, a.size_bytes, a.sha256, s.git_url, s.git_ref, "
    "s.target_url, s.environment FROM public.project_sources s "
    "LEFT JOIN public.artifacts a ON a.id = s.upload_artifact_id "
)
_SNAPSHOT = (
    "id, project_id, source_id, content_sha256, detected, status, error_summary, created_by, "
    "created_at, completed_at"
)


def _snap(row: Any) -> SnapshotRecord:
    data = dict(row._mapping)
    data["content_sha256"] = data["content_sha256"].strip() if data["content_sha256"] else None
    return SnapshotRecord(**data)


def _src(row: Any) -> SourceRecord:
    data = dict(row._mapping)
    data["sha256"] = data["sha256"].strip() if data["sha256"] else None
    return SourceRecord(**data)


# ---- projects ---------------------------------------------------------------


def create_project(
    db: Session, *, name: str, description: str | None, owner_id: uuid.UUID, application_type: str
) -> ProjectRecord:
    row = db.execute(
        text(
            "INSERT INTO public.projects (name, description, owner_user_id, application_type) "
            f"VALUES (:n, :d, :o, :t) RETURNING {_PROJECT}"
        ),
        {"n": name, "d": description, "o": owner_id, "t": application_type},
    ).one()
    return ProjectRecord(**row._mapping)


def get_project(
    db: Session, project_id: uuid.UUID, *, for_update: bool = False
) -> ProjectRecord | None:
    sql = f"SELECT {_PROJECT} FROM public.projects WHERE id = :p" + (
        " FOR UPDATE" if for_update else ""
    )
    row = db.execute(text(sql), {"p": project_id}).first()
    return ProjectRecord(**row._mapping) if row else None


def list_projects(
    db: Session, user_id: uuid.UUID, *, all_projects: bool, include_archived: bool, limit: int
) -> list[tuple[ProjectRecord, list[str]]]:
    """Projects visible to the user with every grant they hold (``read``/``run``/``manage``).
    ``all_projects`` (Super Admin only, decided by the caller) returns every project."""
    rows = db.execute(
        text(
            f"""
            SELECT {", ".join("p." + c.strip() for c in _PROJECT.split(","))}, g.grant_level
            FROM public.projects p
            LEFT JOIN LATERAL (
                SELECT 'manage' AS grant_level WHERE p.owner_user_id = :u
                UNION ALL
                SELECT m.access_level FROM public.project_memberships m
                  WHERE m.project_id = p.id AND m.user_id = :u
                UNION ALL
                SELECT CASE WHEN tm.team_role = 'owner' THEN 'manage' ELSE p.team_access END
                  FROM public.team_memberships tm
                  WHERE tm.team_id = p.team_id AND tm.user_id = :u
                    AND (tm.team_role = 'owner' OR p.team_access <> 'none')
            ) g ON true
            WHERE (:all OR g.grant_level IS NOT NULL)
              AND (:archived OR p.status = 'active')
            ORDER BY p.created_at DESC, p.id
            """
        ),
        {"u": user_id, "all": all_projects, "archived": include_archived},
    ).all()
    grouped: dict[uuid.UUID, tuple[ProjectRecord, list[str]]] = {}
    for row in rows:
        data = dict(row._mapping)
        level = data.pop("grant_level")
        project = ProjectRecord(**data)
        grouped.setdefault(project.id, (project, []))
        if level:
            grouped[project.id][1].append(level)
    return list(grouped.values())[:limit]


def update_project(db: Session, project_id: uuid.UUID, fields: dict[str, Any]) -> None:
    if not fields or not set(fields) <= {"name", "description"}:
        raise ValueError("unsupported project fields")
    assignments = ", ".join(f"{k} = :{k}" for k in fields)
    db.execute(
        text(f"UPDATE public.projects SET {assignments} WHERE id = :id"),
        {**fields, "id": project_id},
    )


def archive_project(db: Session, project_id: uuid.UUID) -> None:
    db.execute(
        text("UPDATE public.projects SET status = 'archived', archived_at = now() WHERE id = :id"),
        {"id": project_id},
    )


# ---- members ----------------------------------------------------------------


def list_members(db: Session, project_id: uuid.UUID) -> list[MemberRecord]:
    rows = db.execute(
        text(
            "SELECT m.user_id, u.email, u.display_name, m.access_level, m.created_at "
            "FROM public.project_memberships m JOIN app_user.users u ON u.id = m.user_id "
            "WHERE m.project_id = :p ORDER BY u.email"
        ),
        {"p": project_id},
    ).all()
    return [MemberRecord(**r._mapping) for r in rows]


def upsert_member(
    db: Session, project_id: uuid.UUID, user_id: uuid.UUID, level: str, granted_by: uuid.UUID
) -> None:
    db.execute(
        text(
            "INSERT INTO public.project_memberships "
            "(project_id, user_id, access_level, granted_by) "
            "VALUES (:p, :u, :l, :g) ON CONFLICT (project_id, user_id) "
            "DO UPDATE SET access_level = EXCLUDED.access_level, granted_by = EXCLUDED.granted_by"
        ),
        {"p": project_id, "u": user_id, "l": level, "g": granted_by},
    )


def delete_member(db: Session, project_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    result = db.execute(
        text("DELETE FROM public.project_memberships WHERE project_id = :p AND user_id = :u"),
        {"p": project_id, "u": user_id},
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


# ---- sources and upload artifacts ---------------------------------------------


def insert_upload_artifact(
    db: Session,
    *,
    project_id: uuid.UUID,
    storage_key: str,
    sha256: str,
    size_bytes: int,
    created_by: uuid.UUID,
) -> uuid.UUID:
    row = db.execute(
        text(
            "INSERT INTO public.artifacts (project_id, kind, storage_key, sha256, size_bytes, "
            "content_type, validation_status, created_by) VALUES "
            "(:p, 'upload', :k, :h, :s, 'application/zip', 'accepted', :c) RETURNING id"
        ),
        {"p": project_id, "k": storage_key, "h": sha256, "s": size_bytes, "c": created_by},
    ).one()
    return uuid.UUID(str(row[0]))


def get_artifact(
    db: Session, project_id: uuid.UUID, artifact_id: uuid.UUID
) -> ArtifactRecord | None:
    row = db.execute(
        text(
            "SELECT id, project_id, storage_key, sha256, size_bytes FROM public.artifacts "
            "WHERE id = :a AND project_id = :p AND deleted_at IS NULL"
        ),
        {"a": artifact_id, "p": project_id},
    ).first()
    if row is None:
        return None
    data = dict(row._mapping)
    data["sha256"] = data["sha256"].strip()
    return ArtifactRecord(**data)


def insert_zip_source(
    db: Session, *, project_id: uuid.UUID, name: str, artifact_id: uuid.UUID, created_by: uuid.UUID
) -> uuid.UUID:
    row = db.execute(
        text(
            "INSERT INTO public.project_sources "
            "(project_id, source_type, name, upload_artifact_id, "
            "created_by) VALUES (:p, 'zip_upload', :n, :a, :c) RETURNING id"
        ),
        {"p": project_id, "n": name, "a": artifact_id, "c": created_by},
    ).one()
    return uuid.UUID(str(row[0]))


def insert_url_source(
    db: Session,
    *,
    project_id: uuid.UUID,
    source_type: str,
    name: str,
    git_url: str | None,
    git_ref: str | None,
    target_url: str | None,
    environment: str | None,
    created_by: uuid.UUID,
) -> uuid.UUID:
    row = db.execute(
        text(
            "INSERT INTO public.project_sources (project_id, source_type, name, git_url, git_ref, "
            "target_url, environment, created_by) VALUES (:p, :t, :n, :gu, :gr, :tu, :e, :c) "
            "RETURNING id"
        ),
        {
            "p": project_id, "t": source_type, "n": name, "gu": git_url, "gr": git_ref,
            "tu": target_url, "e": environment, "c": created_by,
        },
    ).one()  # fmt: skip
    return uuid.UUID(str(row[0]))


def list_sources(db: Session, project_id: uuid.UUID) -> list[SourceRecord]:
    rows = db.execute(
        text(_SOURCE_SELECT + "WHERE s.project_id = :p ORDER BY s.created_at DESC, s.id"),
        {"p": project_id},
    ).all()
    return [_src(r) for r in rows]


def get_source(db: Session, project_id: uuid.UUID, source_id: uuid.UUID) -> SourceRecord | None:
    row = db.execute(
        text(_SOURCE_SELECT + "WHERE s.project_id = :p AND s.id = :s"),
        {"p": project_id, "s": source_id},
    ).first()
    return _src(row) if row else None


def deactivate_source(db: Session, project_id: uuid.UUID, source_id: uuid.UUID) -> None:
    db.execute(
        text(
            "UPDATE public.project_sources SET is_active = false WHERE project_id = :p AND id = :s"
        ),
        {"p": project_id, "s": source_id},
    )


# ---- analysis snapshots -----------------------------------------------------------


def insert_snapshot(
    db: Session,
    *,
    project_id: uuid.UUID,
    source_id: uuid.UUID,
    content_sha256: str | None,
    detected: dict[str, Any],
    status: str,
    error_summary: str | None,
    created_by: uuid.UUID,
) -> SnapshotRecord:
    row = db.execute(
        text(
            "INSERT INTO public.analysis_snapshots "
            "(project_id, source_id, content_sha256, detected, "
            "status, error_summary, created_by, completed_at) VALUES "
            "(:p, :s, :h, CAST(:d AS jsonb), :st, :e, :c, now()) "
            f"RETURNING {_SNAPSHOT}"
        ),
        {
            "p": project_id,
            "s": source_id,
            "h": content_sha256,
            "d": json.dumps(detected),
            "st": status,
            "e": error_summary,
            "c": created_by,
        },
    ).one()
    return _snap(row)


def list_snapshots(db: Session, project_id: uuid.UUID, limit: int) -> list[SnapshotRecord]:
    rows = db.execute(
        text(
            f"SELECT {_SNAPSHOT} FROM public.analysis_snapshots WHERE project_id = :p "
            "ORDER BY created_at DESC, id LIMIT :l"
        ),
        {"p": project_id, "l": limit},
    ).all()
    return [_snap(r) for r in rows]


def get_snapshot(db: Session, snapshot_id: uuid.UUID) -> SnapshotRecord | None:
    row = db.execute(
        text(f"SELECT {_SNAPSHOT} FROM public.analysis_snapshots WHERE id = :i"), {"i": snapshot_id}
    ).first()
    return _snap(row) if row else None
