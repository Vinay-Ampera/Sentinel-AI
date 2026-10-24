"""SQL for ``public.agent_runs`` and ``public.agent_steps`` (workflow records, Stage 11).

Written through short transactions of their own (like ``llm_usage``) so the trace of a
workflow survives when the request that started it fails or rolls back."""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class AgentRunRecord:
    id: uuid.UUID
    project_id: uuid.UUID
    workflow: str
    subject_type: str | None
    subject_id: uuid.UUID | None
    status: str
    degraded_reason: str | None
    requested_by: uuid.UUID | None
    input_hash: str | None
    template_version: str | None
    model: str | None
    used_llm: bool
    cache_hit: bool
    result: dict[str, Any] | None
    started_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True)
class AgentStepRecord:
    seq: int
    node: str
    kind: str
    outcome: str
    detail: dict[str, Any]
    llm_usage_id: int | None
    created_at: datetime


_RUN_COLS = (
    "id, project_id, workflow, subject_type, subject_id, status, degraded_reason, requested_by, "
    "input_hash, template_version, model, used_llm, cache_hit, result, started_at, finished_at"
)


def _run(row: Any) -> AgentRunRecord:
    return AgentRunRecord(
        row.id, row.project_id, row.workflow, row.subject_type, row.subject_id, row.status,
        row.degraded_reason, row.requested_by, row.input_hash, row.template_version, row.model,
        row.used_llm, row.cache_hit, row.result, row.started_at, row.finished_at,
    )  # fmt: skip


def create_run(
    db: Session,
    *,
    project_id: uuid.UUID,
    workflow: str,
    requested_by: uuid.UUID | None,
    subject_type: str | None = None,
    subject_id: uuid.UUID | None = None,
) -> uuid.UUID:
    row = db.execute(
        text(
            "INSERT INTO public.agent_runs (project_id, workflow, requested_by, subject_type, "
            "subject_id) VALUES (:p, :w, :u, :st, :sid) RETURNING id"
        ),
        {"p": project_id, "w": workflow, "u": requested_by, "st": subject_type, "sid": subject_id},
    ).one()
    return row.id  # type: ignore[no-any-return]


def add_step(
    db: Session,
    run_id: uuid.UUID,
    *,
    node: str,
    kind: str,
    outcome: str,
    detail: dict[str, Any],
    llm_usage_id: int | None = None,
) -> int:
    row = db.execute(
        text(
            "INSERT INTO public.agent_steps (agent_run_id, seq, node, kind, outcome, detail, "
            "llm_usage_id) VALUES (:r, (SELECT COALESCE(MAX(seq), 0) + 1 FROM public.agent_steps "
            "WHERE agent_run_id = :r), :n, :k, :o, CAST(:d AS jsonb), :u) RETURNING seq"
        ),
        {
            "r": run_id,
            "n": node,
            "k": kind,
            "o": outcome,
            "d": json.dumps(detail),
            "u": llm_usage_id,
        },
    ).one()
    return int(row.seq)


def finish_run(
    db: Session,
    run_id: uuid.UUID,
    *,
    status: str,
    degraded_reason: str | None,
    used_llm: bool,
    cache_hit: bool,
    model: str | None,
    input_hash: str | None,
    template_version: str | None,
    result: dict[str, Any] | None,
) -> None:
    db.execute(
        text(
            "UPDATE public.agent_runs SET status = :s, degraded_reason = :d, used_llm = :ul, "
            "cache_hit = :ch, model = :m, input_hash = :ih, template_version = :tv, "
            "result = CAST(:res AS jsonb), finished_at = now() "
            "WHERE id = :id AND status = 'running'"
        ),
        {
            "s": status, "d": degraded_reason, "ul": used_llm, "ch": cache_hit, "m": model,
            "ih": input_hash, "tv": template_version, "res": json.dumps(result), "id": run_id,
        },
    )  # fmt: skip


def get_run(db: Session, project_id: uuid.UUID, run_id: uuid.UUID) -> AgentRunRecord | None:
    row = db.execute(
        text(f"SELECT {_RUN_COLS} FROM public.agent_runs WHERE id = :id AND project_id = :p"),
        {"id": run_id, "p": project_id},
    ).first()
    return _run(row) if row else None


def list_runs(db: Session, project_id: uuid.UUID, limit: int) -> list[AgentRunRecord]:
    rows = db.execute(
        text(
            f"SELECT {_RUN_COLS} FROM public.agent_runs WHERE project_id = :p "
            "ORDER BY created_at DESC, id LIMIT :n"
        ),
        {"p": project_id, "n": limit},
    ).all()
    return [_run(r) for r in rows]


def list_steps(db: Session, run_id: uuid.UUID) -> list[AgentStepRecord]:
    rows = db.execute(
        text(
            "SELECT seq, node, kind, outcome, detail, llm_usage_id, created_at "
            "FROM public.agent_steps WHERE agent_run_id = :r ORDER BY seq"
        ),
        {"r": run_id},
    ).all()
    return [
        AgentStepRecord(r.seq, r.node, r.kind, r.outcome, r.detail, r.llm_usage_id, r.created_at)
        for r in rows
    ]


def find_cached_result(
    db: Session, project_id: uuid.UUID, workflow: str, input_hash: str, max_age_hours: int
) -> dict[str, Any] | None:
    """Result of the newest finished run with the same inputs that actually used a model
    (so a cache hit never replays a deterministic or failed outcome)."""
    row = db.execute(
        text(
            "SELECT result FROM public.agent_runs WHERE project_id = :p AND workflow = :w "
            "AND input_hash = :h AND status = 'succeeded' AND used_llm AND NOT cache_hit "
            "AND result IS NOT NULL AND finished_at > now() - make_interval(hours => :age) "
            "ORDER BY finished_at DESC LIMIT 1"
        ),
        {"p": project_id, "w": workflow, "h": input_hash, "age": max_age_hours},
    ).first()
    return row.result if row else None


def close_interrupted(db: Session, older_than_seconds: float) -> int:
    """Runs still ``running`` long after their deadline lost their process: close them as
    failed, and settle model reservations that were never completed (Q109)."""
    runs = db.execute(
        text(
            "UPDATE public.agent_runs SET status = 'failed', degraded_reason = NULL, "
            "result = jsonb_build_object('error', 'interrupted'), finished_at = now() "
            "WHERE status = 'running' AND started_at < now() - make_interval(secs => :s)"
        ),
        {"s": older_than_seconds},
    )
    db.execute(
        text(
            "UPDATE public.llm_usage SET outcome = 'provider_error', input_tokens = 0, "
            "output_tokens = 0, estimated_cost_usd = 0 WHERE outcome = 'reserved' "
            "AND created_at < now() - make_interval(secs => :s)"
        ),
        {"s": older_than_seconds},
    )
    return int(runs.rowcount)  # type: ignore[attr-defined]
