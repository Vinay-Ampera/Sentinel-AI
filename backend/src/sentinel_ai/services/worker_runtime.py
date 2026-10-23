"""Worker-side processing of one batch (Stage 7).

Order of events: claim (only the latest dispatch of a queued batch wins) -> revalidate
authorization, plan integrity and the target gate -> execute each test through the
``Executor`` interface -> record idempotent results -> settle the batch and the run.
Every step re-reads PostgreSQL; the broker message carries nothing but a batch id.

Executors must poll ``should_stop`` (at least every third of the lease): that call renews the
lease, and tells the executor to terminate when cancellation or a timeout was requested or
the batch was taken away from this worker.
"""

import logging
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from sentinel_ai.core.config import Settings
from sentinel_ai.core.permissions import AccessLevel, Permission, has_permission
from sentinel_ai.execution.interface import (
    OUTCOME_STATUSES,
    CaseResult,
    EvidenceItem,
    ExecutionRequest,
    Executor,
    ScanOutcome,
    TargetRef,
    WorkspaceRef,
)
from sentinel_ai.repositories import identity, plans, projects, runs
from sentinel_ai.repositories.plans import PlannedTestRecord
from sentinel_ai.repositories.runs import BatchRecord, RunRecord
from sentinel_ai.services import audit, authorizations, job_state
from sentinel_ai.services import findings as findings_service
from sentinel_ai.services import plans as plans_service
from sentinel_ai.services import policy as policy_service
from sentinel_ai.services import project_access as project_access_service
from sentinel_ai.services.artifact_store import ArtifactStore, sha256_bytes

logger = logging.getLogger(__name__)

APPROVED_TEST = "approved"
SAFE_NAME = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")


@dataclass(frozen=True)
class Revalidation:
    batch_reason: str | None  # the whole batch must not run
    blocked: dict[uuid.UUID, str]  # per-test target-gate refusals


def _stop_reason(db: Session, batch_id: uuid.UUID) -> str | None:
    """'cancel', 'timeout' or None, from the database."""
    row = db.execute(
        text(
            "SELECT status, started_at IS NOT NULL AND started_at + make_interval(secs => "
            "timeout_seconds) < clock_timestamp() FROM public.test_batches WHERE id = :i"
        ),
        {"i": batch_id},
    ).first()
    if row is None:
        return "lost"
    if row[0] == "cancel_requested":
        return "cancel"
    if row[1]:
        return "timeout"
    return None if row[0] in ("dispatched", "running") else "lost"


def revalidate(db: Session, run: RunRecord, tests: list[PlannedTestRecord]) -> Revalidation:
    """Everything that was true at run creation must still be true now."""
    user = identity.get_user(db, run.requested_by)
    if user is None or not user.is_active:
        return Revalidation("The user who started the run is no longer active.", {})
    if not has_permission(user.role_name, Permission.PLAN_AND_RUN):
        return Revalidation("The user who started the run may no longer run tests.", {})
    level = project_access_service.resolve_explicit_access(db, user, run.project_id)
    if level is None or level < AccessLevel.RUN:
        return Revalidation("The user who started the run no longer has run access.", {})
    project = projects.get_project(db, run.project_id)
    if project is None or project.status != "active":
        return Revalidation("The project is no longer active.", {})
    plan = plans.get_plan(db, run.plan_id)
    if plan is None or plan.project_id != run.project_id or plan.status != "approved":
        return Revalidation("The plan is no longer approved.", {})
    if plan.content_sha256 != plans_service.content_hash(plan, tests):
        return Revalidation("The plan no longer matches what was approved.", {})

    gate = authorizations.load_gate_context(
        db, run.project_id, policy_service.load_effective(db, run.project_id)
    )
    blocked: dict[uuid.UUID, str] = {}
    for t in tests:
        target = t.definition.get("target")
        source = uuid.UUID(target["source_id"]) if target else None
        reason = authorizations.gate_reason(gate, source, t.risk_level, t.definition)
        if reason is not None:
            blocked[t.id] = reason
    return Revalidation(None, blocked)


def process_batch(
    factory: sessionmaker[Session],
    settings: Settings,
    executor: Executor,
    batch_id: uuid.UUID,
    task_id: str,
    worker_id: str,
) -> str:
    """Process one delivered batch message. Returns a short outcome label (for tests/logs)."""
    claimed = _claim(factory, settings, batch_id, task_id, worker_id)
    if isinstance(claimed, str):
        return claimed
    run, batch = claimed
    try:
        return _run_batch(factory, settings, executor, run, batch, worker_id)
    except Exception as exc:
        # Unexpected: settle as an infrastructure failure (bounded retry) rather than leave
        # the batch to wait for its lease. If even this fails, the lease reconciler recovers.
        logger.error("batch %s crashed in the worker (%s)", batch_id, type(exc).__name__)
        _fail_infrastructure(factory, settings, batch_id, worker_id, "internal_error")
        return "crashed"


def _claim(
    factory: sessionmaker[Session],
    settings: Settings,
    batch_id: uuid.UUID,
    task_id: str,
    worker_id: str,
) -> tuple[RunRecord, BatchRecord] | str:
    with factory() as db:
        batch = runs.claim_batch(db, batch_id, task_id, worker_id, settings.job_lease_seconds)
        if batch is None:
            db.rollback()
            logger.info("batch %s: stale or duplicate delivery ignored", batch_id)
            return "noop"
        run = runs.get_run(db, batch.run_id, for_update=True)
        assert run is not None
        runs.insert_event(
            db, run.id, "transition", batch_id=batch.id, from_status="queued",
            to_status="dispatched", worker_id=worker_id, detail={"attempt": batch.attempt},
        )  # fmt: skip
        if run.status == "queued":
            runs.transition_run(db, run.id, "queued", "dispatched")
            runs.transition_run(db, run.id, "dispatched", "running", start=True)
            runs.insert_event(
                db, run.id, "transition", from_status="queued", to_status="running",
                worker_id=worker_id,
            )  # fmt: skip
            audit.record(
                db, job_state.SYSTEM_CONTEXT, action="run.start", outcome="success",
                actor_type="worker", project_id=run.project_id, target_type="run",
                target_id=str(run.id), detail={"requested_by": str(run.requested_by)},
            )  # fmt: skip
        elif run.status not in ("dispatched", "running"):
            # Cancelled/timed out between dispatch and claim: nothing may start.
            job_state.batch_to(
                db, _as(batch, "dispatched"), "cancelled", worker_id=worker_id, finish=True,
                detail={"reason": f"run is {run.status}"},
            )  # fmt: skip
            job_state.finalize_run(db, run.id, worker_id=worker_id)
            db.commit()
            return "skipped"
        db.commit()
        return run, batch


def _as(batch: BatchRecord, status: str) -> BatchRecord:
    return BatchRecord(**{**batch.__dict__, "status": status})


def _run_batch(
    factory: sessionmaker[Session],
    settings: Settings,
    executor: Executor,
    run: RunRecord,
    batch: BatchRecord,
    worker_id: str,
) -> str:
    # ---- revalidate, then start ----------------------------------------------------------
    with factory() as db:
        tests = {t.id: t for t in plans.list_tests(db, run.plan_id)}
        item_ids = runs.list_items(db, batch.id)
        batch_tests = [tests[i] for i in item_ids if i in tests]
        check = revalidate(db, run, list(tests.values()))
        if check.batch_reason is not None:
            for test_id in item_ids:
                runs.insert_result(
                    db, run_id=run.id, batch_id=batch.id, planned_test_id=test_id,
                    attempt=batch.attempt, status="blocked", summary=check.batch_reason,
                )  # fmt: skip
            job_state.batch_to(
                db, _as(batch, "dispatched"), "failed", worker_id=worker_id, finish=True,
                error_code="revalidation_failed", error_summary=check.batch_reason,
            )  # fmt: skip
            job_state.finalize_run(db, run.id, worker_id=worker_id)
            db.commit()
            return "blocked"
        if not job_state.batch_to(
            db, _as(batch, "dispatched"), "running", worker_id=worker_id, start=True
        ):
            # Changed under us (cancel requested while dispatched, or reconciled).
            current = runs.get_batch(db, batch.id)
            db.rollback()
            if current is None or current.status != "cancel_requested":
                return "lost"
        else:
            db.commit()

    # ---- execute -------------------------------------------------------------------------
    state: dict[str, str | None] = {"stop": None}

    def should_stop() -> bool:
        with factory() as db:
            if not runs.renew_lease(db, batch.id, worker_id, settings.job_lease_seconds):
                state["stop"] = "lost"
            else:
                state["stop"] = _stop_reason(db, batch.id)
            db.commit()
        return state["stop"] is not None

    already = _already_finished(factory, batch.id)
    for test in batch_tests:
        if test.id in already:
            continue
        if should_stop():
            break
        with factory() as db:
            if test.id in check.blocked:
                runs.insert_result(
                    db, run_id=run.id, batch_id=batch.id, planned_test_id=test.id,
                    attempt=batch.attempt, status="blocked", summary=check.blocked[test.id],
                )  # fmt: skip
                db.commit()
                continue
        with factory() as db:
            workspace = _workspace(db, run, test)  # project-scoped, hash-recorded source only
            target = _target(db, run, test)  # project-scoped remote source, or None
        outcome = executor.execute(
            ExecutionRequest(
                run_id=run.id,
                batch_id=batch.id,
                planned_test_id=test.id,
                check_id=str(test.definition.get("check_id", "")),
                attempt=batch.attempt,
                timeout_seconds=batch.timeout_seconds,
                project_id=run.project_id,
                workspace=workspace,
                parameters=dict(test.definition.get("parameters") or {}),
                target=target,
            ),
            should_stop,
        )
        should_stop()  # re-check ownership: a reconciled batch must not record a late result
        if state["stop"] == "lost":
            return _settle(factory, settings, executor, run, batch, worker_id, "lost")
        valid = outcome.status in OUTCOME_STATUSES
        status = outcome.status if valid else "error"
        summary = outcome.summary if valid else "Executor reported an invalid status."
        if status == "cancelled" and state["stop"] == "timeout":
            status = "timed_out"  # stopped by the batch time limit, not by a person
        with factory() as db:
            result_id = runs.insert_result(
                db, run_id=run.id, batch_id=batch.id, planned_test_id=test.id,
                attempt=batch.attempt, status=status, summary=job_state.clip(summary),
                exit_code=outcome.exit_code, duration_ms=outcome.duration_ms,
            )  # fmt: skip
            db.commit()
        if result_id is not None and outcome.cases:
            _store_cases(factory, run, result_id, outcome.cases)
        stored: dict[str, uuid.UUID] = {}
        if result_id is not None and outcome.evidence:
            stored = _store_evidence(factory, settings, run, result_id, outcome.evidence)
        if result_id is not None and outcome.scan is not None:
            _store_findings(factory, run, test, result_id, outcome.scan, stored)
        if status == "failed_to_start":
            state["stop"] = "failed_to_start"
            break
        if status in ("cancelled", "timed_out"):
            if state["stop"] is None:
                should_stop()  # is the whole batch being cancelled or out of time?
            if state["stop"] is not None:
                break
            if status == "cancelled":
                state["stop"] = "cancel"  # an executor only cancels because it was told to
                break
            # Otherwise this one test hit its own time limit: record it and run the rest.

    return _settle(factory, settings, executor, run, batch, worker_id, state["stop"])


def _workspace(db: Session, run: RunRecord, test: PlannedTestRecord) -> WorkspaceRef | None:
    """The test's uploaded source archive, only if it is an active source of the run's own
    project. Anything else (other project, inactive, not an upload) yields no workspace."""
    target = test.definition.get("target")
    if not isinstance(target, dict):
        return None
    try:
        source_id = uuid.UUID(str(target.get("source_id")))
    except ValueError:
        return None
    source = next((s for s in projects.list_sources(db, run.project_id) if s.id == source_id), None)
    if (
        source is None
        or not source.is_active
        or source.source_type != "zip_upload"
        or source.upload_artifact_id is None
    ):
        return None
    artifact = projects.get_artifact(db, run.project_id, source.upload_artifact_id)
    if artifact is None:
        return None
    return WorkspaceRef(artifact.storage_key, artifact.sha256, artifact.size_bytes)


def _target(db: Session, run: RunRecord, test: PlannedTestRecord) -> TargetRef | None:
    """The test's authorized remote development/staging URL, only if it is an active remote
    source of the run's own project. The target gate already passed in ``revalidate``; the
    executor validates the URL again and ZAP additionally pins the resolved address."""
    target = test.definition.get("target")
    if not isinstance(target, dict):
        return None
    try:
        source_id = uuid.UUID(str(target.get("source_id")))
    except ValueError:
        return None
    source = next((s for s in projects.list_sources(db, run.project_id) if s.id == source_id), None)
    if (
        source is None
        or not source.is_active
        or source.source_type != "remote_url"
        or not source.target_url
        or source.environment not in ("development", "staging")
    ):
        return None
    return TargetRef(url=source.target_url, environment=source.environment, source_id=source.id)


def _store_cases(
    factory: sessionmaker[Session],
    run: RunRecord,
    result_id: uuid.UUID,
    cases: tuple[CaseResult, ...],
) -> None:
    """Keep the individual cases a runner reported. Never loses the committed result."""
    try:
        with factory() as db:
            runs.insert_cases(db, run.id, result_id, cases)
            db.commit()
    except Exception as exc:
        logger.error("cases for result %s could not be stored (%s)", result_id, type(exc).__name__)


def _store_evidence(
    factory: sessionmaker[Session],
    settings: Settings,
    run: RunRecord,
    result_id: uuid.UUID,
    items: tuple[EvidenceItem, ...],
) -> dict[str, uuid.UUID]:
    """Write evidence under server-chosen keys and record it; returns the artifact id per file
    name. A failure here never loses the result that was already committed; it is logged
    without content."""
    store = ArtifactStore(settings.artifact_root())
    limit = settings.sandbox_output_cap_bytes + 4096
    ids: dict[str, uuid.UUID] = {}
    try:
        with factory() as db:
            for item in items:
                if item.kind not in ("log", "report") or not SAFE_NAME.fullmatch(item.name):
                    continue
                data = item.data[:limit]
                key = f"projects/{run.project_id}/runs/{run.id}/results/{result_id}/{item.name}"
                store.put_bytes(key, data)
                ids[item.name] = runs.insert_evidence_artifact(
                    db, project_id=run.project_id, run_id=run.id, result_id=result_id,
                    kind=item.kind, storage_key=key, sha256=sha256_bytes(data),
                    size_bytes=len(data), content_type=item.content_type, filename=item.name,
                )  # fmt: skip
            db.commit()
    except Exception as exc:
        ids = {}
        logger.error(
            "evidence for result %s could not be stored (%s)", result_id, type(exc).__name__
        )
    return ids


def _store_findings(
    factory: sessionmaker[Session],
    run: RunRecord,
    test: PlannedTestRecord,
    result_id: uuid.UUID,
    scan: ScanOutcome,
    stored: dict[str, uuid.UUID],
) -> None:
    """Record scanner findings, each linked to the stored scan report. The committed result
    is never lost if this fails; the failure is logged without content."""
    target = test.definition.get("target")
    try:
        source_id = uuid.UUID(str(target.get("source_id"))) if isinstance(target, dict) else None
    except ValueError:
        source_id = None
    report = stored.get(f"{scan.tool}.json")
    try:
        with factory() as db:
            # Never trust a source id the plan did not scope to this project.
            if source_id is not None and not any(
                s.id == source_id for s in projects.list_sources(db, run.project_id)
            ):
                source_id = None
            findings_service.ingest_scan(
                db, project_id=run.project_id, run_id=run.id, result_id=result_id,
                source_id=source_id, scan=scan, report_artifact_id=report,
            )  # fmt: skip
            db.commit()
    except Exception as exc:
        logger.error(
            "findings for result %s could not be stored (%s)", result_id, type(exc).__name__
        )


def _already_finished(factory: sessionmaker[Session], batch_id: uuid.UUID) -> set[uuid.UUID]:
    with factory() as db:
        return runs.finished_test_ids(db, batch_id)


def _settle(
    factory: sessionmaker[Session],
    settings: Settings,
    executor: Executor,
    run: RunRecord,
    batch: BatchRecord,
    worker_id: str,
    stop: str | None,
) -> str:
    if stop == "lost":
        logger.warning("batch %s was taken over by the reconciler; worker stops", batch.id)
        return "lost"
    terminated = True
    if stop in ("cancel", "timeout", "failed_to_start"):
        terminated = executor.terminate(batch.id)  # always attempted, outcome recorded
    with factory() as db:
        current = runs.get_batch(db, batch.id, for_update=True)
        if current is None or current.status not in ("running", "cancel_requested"):
            db.rollback()
            return "lost"
        if stop == "failed_to_start":
            if current.attempt < current.max_attempts and job_state.requeue_batch(
                db, current, base_backoff=settings.job_retry_backoff_seconds,
                worker_id=worker_id, reason="failed_to_start",
            ):  # fmt: skip
                outcome = "retry"
            else:
                job_state.mark_unrun(
                    db, run, current, "not_run", "Not run: the batch failed to start."
                )
                job_state.batch_to(
                    db, current, "failed", worker_id=worker_id, finish=True,
                    error_code="failed_to_start",
                    error_summary="The sandbox could not be started; no test result was produced.",
                )  # fmt: skip
                outcome = "failed"
        elif stop == "cancel":
            job_state.mark_unrun(db, run, current, "not_run", "Not run: the run was cancelled.")
            if terminated:
                job_state.batch_to(
                    db, current, "cancelled", worker_id=worker_id, finish=True,
                    detail={"termination_confirmed": True},
                )  # fmt: skip
                outcome = "cancelled"
            else:
                job_state.batch_to(
                    db, current, "failed", worker_id=worker_id, finish=True,
                    error_code="cancel_unconfirmed",
                    error_summary="Cancellation was requested but termination could not be confirmed.",
                )  # fmt: skip
                outcome = "failed"
        elif stop == "timeout":
            job_state.mark_unrun(db, run, current, "not_run", "Not run: the batch timed out.")
            job_state.batch_to(
                db, current, "timed_out", event_type="timeout", worker_id=worker_id, finish=True,
                error_code="timeout", error_summary="The batch exceeded its time limit.",
                detail={"termination_confirmed": terminated},
            )  # fmt: skip
            outcome = "timed_out"
        else:
            results = runs.list_results(db, run.id, status=None, limit=100000)
            mine = [r for r in results if r.batch_id == batch.id]
            if mine and all(r.status == "blocked" for r in mine):
                job_state.batch_to(
                    db, current, "failed", worker_id=worker_id, finish=True,
                    error_code="blocked_by_policy",
                    error_summary="Every test in the batch was blocked before execution.",
                )  # fmt: skip
                outcome = "failed"
            else:
                job_state.batch_to(db, current, "completed", worker_id=worker_id, finish=True)
                outcome = "completed"
        job_state.finalize_run(db, run.id, worker_id=worker_id)
        db.commit()
        return outcome


def _fail_infrastructure(
    factory: sessionmaker[Session],
    settings: Settings,
    batch_id: uuid.UUID,
    worker_id: str,
    code: str,
) -> None:
    try:
        with factory() as db:
            current = runs.get_batch(db, batch_id, for_update=True)
            if current is None or current.status not in ("dispatched", "running"):
                db.rollback()
                return
            if current.attempt < current.max_attempts:
                job_state.requeue_batch(
                    db, current, base_backoff=settings.job_retry_backoff_seconds,
                    worker_id=worker_id, reason=code,
                )  # fmt: skip
            else:
                job_state.batch_to(
                    db, current, "failed", worker_id=worker_id, finish=True, error_code=code,
                    error_summary="The worker hit an internal error while processing this batch.",
                )  # fmt: skip
                job_state.finalize_run(db, current.run_id, worker_id=worker_id)
            db.commit()
    except Exception as exc:  # leave it to the lease reconciler
        logger.error("could not settle batch %s after a crash (%s)", batch_id, type(exc).__name__)
