"""Create, cancel and read test runs (Stage 7).

A run is created only from an approved plan whose content still matches the hash that was
approved, and only if every test still passes the target gate. Nothing here accepts a
command, a risk level or an approval flag. Execution happens in the worker, which repeats
these checks (``worker_runtime``).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from sentinel_ai.core.config import Settings
from sentinel_ai.core.errors import DomainError
from sentinel_ai.core.permissions import AccessLevel
from sentinel_ai.repositories import plans, projects, runs
from sentinel_ai.repositories.identity import UserRecord
from sentinel_ai.repositories.runs import (
    BatchRecord,
    CaseRecord,
    EventRecord,
    EvidenceRecord,
    ResultRecord,
    RunRecord,
)
from sentinel_ai.services import audit, authorizations, job_state
from sentinel_ai.services import plans as plans_service
from sentinel_ai.services import policy as policy_service
from sentinel_ai.services import project_access as project_access_service
from sentinel_ai.services.artifact_store import ArtifactStore, sha256_bytes
from sentinel_ai.services.audit import RequestContext

APPROVED_TEST = "approved"
MIN_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class Progress:
    batches_total: int
    batches_by_status: dict[str, int]
    tests_total: int
    results_by_status: dict[str, int]
    cases_by_status: dict[str, int]


@dataclass(frozen=True)
class ResultDetail:
    result: ResultRecord
    cases: list[CaseRecord]
    evidence: list[EvidenceRecord]


@dataclass(frozen=True)
class RunView:
    run: RunRecord
    progress: Progress | None


def _progress(db: Session, run_id: uuid.UUID) -> Progress:
    by_batch = runs.batch_status_counts(db, run_id)
    return Progress(
        batches_total=sum(by_batch.values()),
        batches_by_status=by_batch,
        tests_total=runs.item_count(db, run_id),
        results_by_status=runs.result_status_counts(db, run_id),
        cases_by_status=runs.case_status_counts(db, run_id),
    )


def _lock_active_project(db: Session, project_id: uuid.UUID) -> None:
    project = projects.get_project(db, project_id, for_update=True)
    if project is None:
        raise DomainError(404, "not_found", "Project not found")
    if project.status != "active":
        raise DomainError(409, "project_archived", "Archived projects are read-only")


def create_run(
    db: Session,
    ctx: RequestContext,
    user: UserRecord,
    settings: Settings,
    *,
    project_id: uuid.UUID,
    plan_id: uuid.UUID,
    timeout_seconds: int | None,
    idempotency_key: str | None,
) -> tuple[RunRecord, bool]:
    """Returns (run, created). A repeated idempotency key returns the original run."""
    project_access_service.authorize_project(db, ctx, user, project_id, AccessLevel.RUN)
    _lock_active_project(db, project_id)  # serialises run creation per project

    if idempotency_key:
        existing = runs.get_run_by_key(db, project_id, idempotency_key)
        if existing is not None:
            if existing.plan_id != plan_id:
                raise DomainError(
                    409, "idempotency_conflict", "That Idempotency-Key was used for another plan"
                )
            return existing, False

    plan = plans.get_plan(db, plan_id, for_update=True)
    if plan is None or plan.project_id != project_id:  # other project: same 404
        raise DomainError(404, "not_found", "Plan not found")
    if plan.status != "approved":
        _refuse(db, ctx, user, project_id, plan_id, "approval_required")
        raise DomainError(409, "approval_required", "Only an approved plan can be run")
    if runs.active_run_for_plan(db, plan_id) is not None:
        raise DomainError(409, "run_already_active", "This plan already has a run in progress")

    tests = plans.list_tests(db, plan_id)
    if plan.content_sha256 != plans_service.content_hash(plan, tests):
        _refuse(db, ctx, user, project_id, plan_id, "plan_changed")
        raise DomainError(409, "plan_changed", "The plan no longer matches what was approved")
    runnable = [t for t in tests if t.status == APPROVED_TEST]
    if not runnable:
        raise DomainError(422, "no_runnable_tests", "The plan has no approved test to run")

    policy = policy_service.load_effective(db, project_id)
    gate = authorizations.load_gate_context(db, project_id, policy)
    blocked = []
    for t in runnable:
        source = (
            t.definition.get("target", {}).get("source_id") if t.definition.get("target") else None
        )
        reason = authorizations.gate_reason(
            gate, uuid.UUID(source) if source else None, t.risk_level, t.definition
        )
        if reason is not None:
            blocked.append({"field": t.name, "issue": reason})
    if blocked:
        _refuse(db, ctx, user, project_id, plan_id, "policy_blocked")
        raise DomainError(409, "policy_blocked", "Some tests are blocked by target policy", blocked)

    timeout = timeout_seconds or settings.job_run_timeout_seconds
    run = runs.insert_run(
        db,
        project_id=project_id,
        plan_id=plan_id,
        requested_by=user.id,
        timeout_seconds=timeout,
        idempotency_key=idempotency_key,
    )
    size = settings.job_batch_size
    ordered = sorted(runnable, key=lambda t: t.ordinal)
    chunks = [ordered[i : i + size] for i in range(0, len(ordered), size)]
    for number, chunk in enumerate(chunks, start=1):
        batch = runs.insert_batch(
            db,
            run.id,
            number,
            max_attempts=settings.job_max_attempts,
            timeout_seconds=settings.job_batch_timeout_seconds,
        )
        for position, test in enumerate(chunk, start=1):
            runs.insert_item(db, batch.id, run.id, test.id, position)
    runs.insert_event(
        db,
        run.id,
        "note",
        to_status="queued",
        actor_user_id=user.id,
        detail={"event": "created", "batches": len(chunks), "tests": len(ordered)},
    )
    audit.record(
        db, ctx, action="run.create", outcome="success", actor_user_id=user.id,
        project_id=project_id, target_type="run", target_id=str(run.id),
        detail={"plan_id": str(plan_id), "content_sha256": plan.content_sha256,
                "batches": len(chunks), "tests": len(ordered), "timeout_seconds": timeout},
    )  # fmt: skip
    db.commit()  # the worker must be able to see the run before anything is enqueued
    return run, True


def _refuse(
    db: Session,
    ctx: RequestContext,
    user: UserRecord,
    project_id: uuid.UUID,
    plan_id: uuid.UUID,
    why: str,
) -> None:
    """Audit a refused start, persisting it before the error rolls the request back."""
    audit.record(
        db, ctx, action="run.create", outcome="denied", actor_user_id=user.id,
        project_id=project_id, target_type="plan", target_id=str(plan_id), detail={"reason": why},
    )  # fmt: skip
    db.commit()


def _authorized_run(
    db: Session, ctx: RequestContext, user: UserRecord, run_id: uuid.UUID, level: AccessLevel
) -> RunRecord:
    run = runs.get_run(db, run_id)
    if run is None:
        raise DomainError(404, "not_found", "Run not found")
    project_access_service.authorize_project(db, ctx, user, run.project_id, level)
    return run


def get_run(db: Session, ctx: RequestContext, user: UserRecord, run_id: uuid.UUID) -> RunView:
    run = _authorized_run(db, ctx, user, run_id, AccessLevel.READ)
    return RunView(run, _progress(db, run_id))


def list_runs(db: Session, project_id: uuid.UUID, limit: int) -> list[RunRecord]:
    return runs.list_runs(db, project_id, limit)


def list_batches(
    db: Session, ctx: RequestContext, user: UserRecord, run_id: uuid.UUID
) -> list[BatchRecord]:
    _authorized_run(db, ctx, user, run_id, AccessLevel.READ)
    return runs.list_batches(db, run_id)


def get_batch(
    db: Session, ctx: RequestContext, user: UserRecord, batch_id: uuid.UUID
) -> BatchRecord:
    batch = runs.get_batch(db, batch_id)
    if batch is None:
        raise DomainError(404, "not_found", "Batch not found")
    _authorized_run(db, ctx, user, batch.run_id, AccessLevel.READ)
    return batch


def list_results(
    db: Session, ctx: RequestContext, user: UserRecord, run_id: uuid.UUID, status: str | None
) -> list[ResultRecord]:
    _authorized_run(db, ctx, user, run_id, AccessLevel.READ)
    return runs.list_results(db, run_id, status=status, limit=1000)


MAX_CASES_SHOWN = 1000
MAX_EVIDENCE_BYTES = 20 * 1024 * 1024


def get_result_detail(
    db: Session, ctx: RequestContext, user: UserRecord, run_id: uuid.UUID, result_id: uuid.UUID
) -> ResultDetail:
    _authorized_run(db, ctx, user, run_id, AccessLevel.READ)
    result = runs.get_result(db, run_id, result_id)  # scoped to the authorized run
    if result is None:
        raise DomainError(404, "not_found", "Result not found")
    return ResultDetail(
        result,
        runs.list_cases(db, result_id, limit=MAX_CASES_SHOWN),
        runs.list_result_evidence(db, result_id),
    )


def read_evidence(
    db: Session,
    ctx: RequestContext,
    user: UserRecord,
    settings: Settings,
    artifact_id: uuid.UUID,
) -> tuple[EvidenceRecord, bytes]:
    """Evidence bytes for a run artifact, only through the project grant (or an audited,
    read-only break-glass grant). The stored hash is re-checked before serving."""
    record = runs.get_evidence(db, artifact_id)
    if record is None:
        raise DomainError(404, "not_found", "Evidence not found")
    project_access_service.authorize_project(db, ctx, user, record.project_id, AccessLevel.READ)
    if record.size_bytes > MAX_EVIDENCE_BYTES:
        raise DomainError(413, "payload_too_large", "Evidence is too large to download here")
    try:
        path = ArtifactStore(settings.artifact_root()).path_for(record.storage_key)
        if path.is_symlink() or not path.is_file():
            raise OSError("missing")
        data = path.read_bytes()
    except (ValueError, OSError):
        raise DomainError(404, "not_found", "Evidence file is not available") from None
    if sha256_bytes(data) != record.sha256:
        audit.record(
            db, ctx, action="artifact.download", outcome="denied", actor_user_id=user.id,
            project_id=record.project_id, target_type="artifact", target_id=str(record.id),
            detail={"reason": "hash_mismatch"},
        )  # fmt: skip
        db.commit()
        raise DomainError(409, "artifact_corrupt", "Stored evidence no longer matches its hash")
    audit.record(
        db, ctx, action="artifact.download", outcome="success", actor_user_id=user.id,
        project_id=record.project_id, target_type="artifact", target_id=str(record.id),
        detail={"name": record.filename, "size_bytes": record.size_bytes, "run_id": str(record.run_id)},
    )  # fmt: skip
    return record, data


def list_events(
    db: Session, ctx: RequestContext, user: UserRecord, run_id: uuid.UUID, after: int
) -> list[EventRecord]:
    _authorized_run(db, ctx, user, run_id, AccessLevel.READ)
    return runs.list_events(db, run_id, after=after, limit=500)


def cancel_run(db: Session, ctx: RequestContext, user: UserRecord, run_id: uuid.UUID) -> RunView:
    """Idempotent. Queued work is cancelled at once; claimed work is asked to stop and the
    worker reports the outcome. Batches that already completed keep their results."""
    known = _authorized_run(db, ctx, user, run_id, AccessLevel.RUN)
    run = runs.get_run(db, run_id, for_update=True)
    assert run is not None
    if run.status not in runs.ACTIVE or run.status == "cancel_requested":
        return RunView(run, _progress(db, run_id))  # terminal or already cancelling: no-op

    batches = runs.list_batches(db, run_id, for_update=True)  # worker claims wait on these locks
    stopped = 0
    for b in batches:
        if b.status in ("queued", "blocked"):
            job_state.mark_unrun(db, run, b, "not_run", "Not run: the run was cancelled before this batch started.")  # fmt: skip
            stopped += job_state.batch_to(
                db, b, "cancelled", actor_user_id=user.id, finish=True,
                detail={"reason": "cancelled before start"},
            )  # fmt: skip
        elif b.status in ("dispatched", "running"):
            stopped += job_state.batch_to(
                db, b, "cancel_requested", event_type="cancel_requested", actor_user_id=user.id
            )
    previous = run.status
    target = "cancelled" if previous == "queued" else "cancel_requested"
    runs.transition_run(
        db, run_id, previous, target, finish=target == "cancelled", cancel_by=user.id
    )
    runs.insert_event(
        db, run_id, "cancel_requested", from_status=previous, to_status=target,
        actor_user_id=user.id, detail={"batches_affected": stopped},
    )  # fmt: skip
    audit.record(
        db, ctx, action="run.cancel", outcome="success", actor_user_id=user.id,
        project_id=known.project_id, target_type="run", target_id=str(run_id),
        detail={"from": previous, "to": target},
    )  # fmt: skip
    if target == "cancel_requested":
        job_state.finalize_run(db, run_id)  # nothing left to stop: settle immediately
    after = runs.get_run(db, run_id)
    assert after is not None
    return RunView(after, _progress(db, run_id))
