"""Projects, membership, ZIP sources, and deterministic analysis (Stage 5).

Authorization is decided by the API dependencies (role permission + project access
level) before these functions run; they additionally enforce project state (archived
projects are read-only) and scope every child lookup by ``project_id``.
"""

import logging
import uuid
import zipfile
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sentinel_ai.core.config import Settings
from sentinel_ai.core.errors import DomainError
from sentinel_ai.core.permissions import AccessLevel, access_level_from_name
from sentinel_ai.repositories import identity, projects
from sentinel_ai.repositories.identity import UserRecord
from sentinel_ai.repositories.projects import (
    MemberRecord,
    ProjectRecord,
    SnapshotRecord,
    SourceRecord,
)
from sentinel_ai.services import analyzer, archive, audit
from sentinel_ai.services import project_access as project_access_service
from sentinel_ai.services import source_validation as sv
from sentinel_ai.services.archive import ArchiveLimits, ArchiveRejected
from sentinel_ai.services.artifact_store import ArtifactStore, sha256_file
from sentinel_ai.services.audit import RequestContext

logger = logging.getLogger(__name__)
APPLICATION_TYPES = ("web_app", "rest_api", "ai_app")
MEMBER_LEVELS = ("read", "run", "manage")


_NOT_ANALYSABLE = {
    "git_repository": "Analysing a Git source needs a clone inside the Stage 8 sandbox "
    "(and credentials design, Q25); only the descriptor is recorded",
    "localhost_url": "Analysing a localhost URL needs sandbox-to-localhost access (Q26, Stage 8)",
    "remote_url": "Analysing a remote URL needs an approved target authorization (Stage 6) "
    "and the Stage 8 sandbox",
}


def archive_limits(settings: Settings) -> ArchiveLimits:
    return ArchiveLimits(
        max_upload_bytes=settings.upload_max_mb * 1024 * 1024,
        max_uncompressed_bytes=settings.zip_max_uncompressed_mb * 1024 * 1024,
        max_files=settings.zip_max_files,
    )


def _active_project(db: Session, project_id: uuid.UUID) -> ProjectRecord:
    project = projects.get_project(db, project_id, for_update=True)
    if project is None:  # authorization already passed; this is a race with deletion
        raise DomainError(404, "not_found", "Project not found")
    if project.status != "active":
        raise DomainError(409, "project_archived", "Archived projects are read-only")
    return project


# ---- projects --------------------------------------------------------------------


def create_project(
    db: Session,
    ctx: RequestContext,
    user: UserRecord,
    *,
    name: str,
    description: str | None,
    application_type: str,
) -> ProjectRecord:
    if application_type not in APPLICATION_TYPES:
        raise DomainError(422, "validation_failed", "Unknown application type")
    try:
        project = projects.create_project(
            db,
            name=name.strip(),
            description=description,
            owner_id=user.id,
            application_type=application_type,
        )
    except IntegrityError:
        db.rollback()
        raise DomainError(409, "conflict", "You already have a project with this name") from None
    audit.record(
        db,
        ctx,
        action="project.create",
        outcome="success",
        actor_user_id=user.id,
        target_type="project",
        target_id=str(project.id),
        project_id=project.id,
    )
    return project


def list_projects(
    db: Session, ctx: RequestContext, user: UserRecord, *, include_archived: bool, limit: int
) -> list[tuple[ProjectRecord, AccessLevel | None]]:
    """Only projects the caller holds a grant on, whatever the role."""
    rows = projects.list_projects(
        db, user.id, all_projects=False, include_archived=include_archived, limit=limit
    )
    result = []
    for project, grants in rows:
        levels = [lv for g in grants if (lv := access_level_from_name(g)) is not None]
        result.append((project, max(levels, default=None)))
    return result


def get_project(db: Session, project_id: uuid.UUID) -> ProjectRecord:
    project = projects.get_project(db, project_id)
    if project is None:
        raise DomainError(404, "not_found", "Project not found")
    return project


def update_project(
    db: Session,
    ctx: RequestContext,
    user: UserRecord,
    project_id: uuid.UUID,
    *,
    name: str | None,
    description: str | None,
) -> ProjectRecord:
    _active_project(db, project_id)
    fields: dict[str, object] = {}
    if name is not None:
        fields["name"] = name.strip()
    if description is not None:
        fields["description"] = description
    if fields:
        try:
            projects.update_project(db, project_id, fields)
        except IntegrityError:
            db.rollback()
            raise DomainError(
                409, "conflict", "The owner already has a project with this name"
            ) from None
        audit.record(
            db,
            ctx,
            action="project.update",
            outcome="success",
            actor_user_id=user.id,
            target_type="project",
            target_id=str(project_id),
            project_id=project_id,
            detail={"fields": sorted(fields)},
        )
    return get_project(db, project_id)


def archive_project(
    db: Session, ctx: RequestContext, user: UserRecord, project_id: uuid.UUID
) -> ProjectRecord:
    _active_project(db, project_id)
    projects.archive_project(db, project_id)
    audit.record(
        db,
        ctx,
        action="project.archive",
        outcome="success",
        actor_user_id=user.id,
        target_type="project",
        target_id=str(project_id),
        project_id=project_id,
    )
    return get_project(db, project_id)


# ---- members ---------------------------------------------------------------------


def list_members(db: Session, project_id: uuid.UUID) -> list[MemberRecord]:
    return projects.list_members(db, project_id)


def set_member(
    db: Session,
    ctx: RequestContext,
    actor: UserRecord,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    level: str,
) -> None:
    project = _active_project(db, project_id)
    if level not in MEMBER_LEVELS:
        raise DomainError(422, "validation_failed", "access_level must be read, run, or manage")
    target = identity.get_user(db, user_id)
    if target is None or not target.is_active:
        raise DomainError(404, "not_found", "User not found")
    if target.id == project.owner_user_id:
        raise DomainError(409, "conflict", "The project owner already has full access")
    projects.upsert_member(db, project_id, user_id, level, actor.id)
    audit.record(
        db,
        ctx,
        action="project.member_set",
        outcome="success",
        actor_user_id=actor.id,
        target_type="user",
        target_id=str(user_id),
        project_id=project_id,
        detail={"access_level": level},
    )


def remove_member(
    db: Session, ctx: RequestContext, actor: UserRecord, project_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    _active_project(db, project_id)
    if not projects.delete_member(db, project_id, user_id):
        raise DomainError(404, "not_found", "Membership not found")
    audit.record(
        db,
        ctx,
        action="project.member_remove",
        outcome="success",
        actor_user_id=actor.id,
        target_type="user",
        target_id=str(user_id),
        project_id=project_id,
    )


# ---- sources ---------------------------------------------------------------------


def register_zip_source(
    db: Session,
    ctx: RequestContext,
    settings: Settings,
    user: UserRecord,
    project_id: uuid.UUID,
    *,
    name: str,
    temp_path: Path,
) -> SourceRecord:
    """Validate an uploaded ZIP (already streamed to ``temp_path`` within the size cap) and
    register it. The temp file is always consumed or removed."""
    store = ArtifactStore(settings.artifact_root())
    try:
        _active_project(db, project_id)
        limits = archive_limits(settings)
        size = temp_path.stat().st_size
        try:
            if size == 0 or not archive.has_zip_magic(temp_path):
                raise ArchiveRejected("invalid_archive", "File is not a valid ZIP archive")
            with archive.open_archive(temp_path) as zf:
                entries = archive.inspect_archive(zf, limits)
                if not any(not e.is_dir for e in entries):
                    raise ArchiveRejected("empty_archive", "Archive contains no files")
        except ArchiveRejected as exc:
            audit.record(
                db,
                ctx,
                action="source.upload",
                outcome="failure",
                actor_user_id=user.id,
                project_id=project_id,
                detail={"reason": exc.code, "size_bytes": size},
            )
            db.commit()
            raise DomainError(exc.status_code, exc.code, exc.message) from None

        digest = sha256_file(temp_path)
        key = store.new_upload_key(project_id)
        store.commit(temp_path, key)
        try:
            artifact_id = projects.insert_upload_artifact(
                db,
                project_id=project_id,
                storage_key=key,
                sha256=digest,
                size_bytes=size,
                created_by=user.id,
            )
            source_id = projects.insert_zip_source(
                db, project_id=project_id, name=name, artifact_id=artifact_id, created_by=user.id
            )
            audit.record(
                db,
                ctx,
                action="source.create",
                outcome="success",
                actor_user_id=user.id,
                target_type="source",
                target_id=str(source_id),
                project_id=project_id,
                detail={"source_type": "zip_upload", "size_bytes": size, "files": len(entries)},
            )
            db.flush()
        except Exception:
            store.remove(key)
            raise
        source = projects.get_source(db, project_id, source_id)
        assert source is not None
        return source
    finally:
        temp_path.unlink(missing_ok=True)


def register_url_source(
    db: Session,
    ctx: RequestContext,
    user: UserRecord,
    project_id: uuid.UUID,
    *,
    source_type: str,
    name: str,
    git_url: str | None,
    git_ref: str | None,
    target_url: str | None,
    environment: str | None,
) -> SourceRecord:
    """Record a Git / localhost / remote descriptor after strict validation. Nothing is
    fetched, cloned, resolved or probed; contacting a target needs Stage 6 authorization
    and Stage 8 sandboxing."""
    _active_project(db, project_id)
    fields = {
        "git_url": git_url,
        "git_ref": git_ref,
        "target_url": target_url,
        "environment": environment,
    }
    allowed = {
        "git_repository": {"git_url", "git_ref"},
        "localhost_url": {"target_url"},
        "remote_url": {"target_url", "environment"},
    }
    if source_type == "zip_upload":
        raise DomainError(422, "validation_failed", "Upload ZIP sources with /sources/zip")
    if source_type not in allowed:
        raise DomainError(422, "validation_failed", "Unknown source_type")
    extra = sorted(k for k, v in fields.items() if v is not None and k not in allowed[source_type])
    if extra:
        raise DomainError(
            422, "validation_failed", f"Fields not allowed for {source_type}: {', '.join(extra)}"
        )
    stored: dict[str, str | None] = {k: None for k in fields}
    try:
        if source_type == "git_repository":
            if git_url is None:
                raise sv.SourceRejected("invalid_url", "git_url is required")
            stored["git_url"] = sv.validate_git_url(git_url).url
            stored["git_ref"] = sv.validate_git_ref(git_ref)
        elif source_type == "localhost_url":
            if target_url is None:
                raise sv.SourceRejected("invalid_url", "target_url is required")
            stored["target_url"] = sv.validate_localhost_url(target_url).url
            stored["environment"] = "local"
        else:
            if target_url is None or environment is None:
                raise sv.SourceRejected("invalid_url", "target_url and environment are required")
            stored["target_url"] = sv.validate_remote_url(target_url, environment).url
            stored["environment"] = environment
    except sv.SourceRejected as exc:
        outcome = "denied" if exc.code == "production_blocked" else "failure"
        audit.record(
            db,
            ctx,
            action="source.create",
            outcome=outcome,
            actor_user_id=user.id,
            project_id=project_id,
            detail={"source_type": source_type, "reason": exc.code},
        )
        db.commit()
        raise DomainError(422, exc.code, exc.message) from None
    source_id = projects.insert_url_source(
        db, project_id=project_id, source_type=source_type, name=name.strip(),
        git_url=stored["git_url"], git_ref=stored["git_ref"], target_url=stored["target_url"],
        environment=stored["environment"], created_by=user.id,
    )  # fmt: skip
    audit.record(
        db, ctx, action="source.create", outcome="success", actor_user_id=user.id,
        target_type="source", target_id=str(source_id), project_id=project_id,
        detail={"source_type": source_type, "environment": stored["environment"]},
    )  # fmt: skip
    db.flush()
    source = projects.get_source(db, project_id, source_id)
    assert source is not None
    return source


def list_sources(db: Session, project_id: uuid.UUID) -> list[SourceRecord]:
    return projects.list_sources(db, project_id)


def deactivate_source(
    db: Session, ctx: RequestContext, user: UserRecord, project_id: uuid.UUID, source_id: uuid.UUID
) -> None:
    _active_project(db, project_id)
    if projects.get_source(db, project_id, source_id) is None:
        raise DomainError(404, "not_found", "Source not found")
    projects.deactivate_source(db, project_id, source_id)
    audit.record(
        db,
        ctx,
        action="source.deactivate",
        outcome="success",
        actor_user_id=user.id,
        target_type="source",
        target_id=str(source_id),
        project_id=project_id,
    )


# ---- analysis --------------------------------------------------------------------


def run_analysis(
    db: Session,
    ctx: RequestContext,
    settings: Settings,
    user: UserRecord,
    project_id: uuid.UUID,
    source_id: uuid.UUID,
) -> SnapshotRecord:
    """Analyse a registered ZIP source: read-only, no extraction, no code executed. A
    failure that is the archive's fault is persisted as a ``failed`` snapshot."""
    project = _active_project(db, project_id)
    source = projects.get_source(db, project_id, source_id)  # scoped: other projects -> 404
    if source is None:
        raise DomainError(404, "not_found", "Source not found")
    if not source.is_active:
        raise DomainError(409, "source_inactive", "This source has been deactivated")
    if source.source_type != "zip_upload" or source.upload_artifact_id is None:
        raise DomainError(
            422, "analysis_not_available", _NOT_ANALYSABLE.get(source.source_type, "Not analysable")
        )
    artifact = projects.get_artifact(db, project_id, source.upload_artifact_id)
    if artifact is None:
        raise DomainError(409, "artifact_missing", "The source archive is no longer available")

    store = ArtifactStore(settings.artifact_root())
    detected: dict[str, object] = {}
    error: str | None = None
    digest: str | None = artifact.sha256
    try:
        path = store.path_for(artifact.storage_key)
        if not path.is_file():
            raise ArchiveRejected("artifact_missing", "The stored archive file is missing")
        if sha256_file(path) != artifact.sha256:
            raise ArchiveRejected(
                "integrity_mismatch", "Stored archive does not match its recorded hash"
            )
        with archive.open_archive(path) as zf:
            entries = archive.inspect_archive(zf, archive_limits(settings))
            detected = analyzer.analyze(zf, entries, project.application_type)
    except ArchiveRejected as exc:
        error = f"{exc.code}: {exc.message}"
    except (zipfile.BadZipFile, OSError, ValueError):
        logger.exception("analysis failed for source %s", source_id)
        error = "analysis_error: the archive could not be analysed"
    snapshot = projects.insert_snapshot(
        db,
        project_id=project_id,
        source_id=source_id,
        content_sha256=digest,
        detected=detected,
        status="failed" if error else "completed",
        error_summary=error,
        created_by=user.id,
    )
    audit.record(
        db,
        ctx,
        action="analysis.run",
        outcome="failure" if error else "success",
        actor_user_id=user.id,
        target_type="analysis",
        target_id=str(snapshot.id),
        project_id=project_id,
        detail={"source_id": str(source_id)},
    )
    return snapshot


def list_snapshots(db: Session, project_id: uuid.UUID, limit: int) -> list[SnapshotRecord]:
    return projects.list_snapshots(db, project_id, limit)


def get_snapshot(
    db: Session, ctx: RequestContext, user: UserRecord, snapshot_id: uuid.UUID
) -> SnapshotRecord | None:
    """Return the snapshot only if the caller can read its project, else None (404)."""
    snapshot = projects.get_snapshot(db, snapshot_id)
    if snapshot is None:
        return None
    level = project_access_service.resolve_access(db, user, snapshot.project_id)
    if level is None:
        return None
    project_access_service.note_break_glass_use(
        db, ctx, user, snapshot.project_id, AccessLevel.READ
    )
    return snapshot
