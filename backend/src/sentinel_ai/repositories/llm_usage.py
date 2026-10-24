"""SQL for ``public.llm_usage`` (one row per gateway call, written in its own transactions so
accounting survives a caller's rollback)."""

import uuid
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

# One lock serializes "check budget, then reserve" across all workers/processes. It is held
# only for these two statements, never across a model call.
_BUDGET_LOCK_KEY = "sentinel.llm_budget"


def lock_budget(db: Session) -> None:
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": _BUDGET_LOCK_KEY})


def run_totals(db: Session, agent_run_id: uuid.UUID) -> tuple[int, Decimal]:
    row = db.execute(
        text(
            "SELECT COALESCE(SUM(input_tokens + output_tokens), 0) AS tokens, "
            "COALESCE(SUM(estimated_cost_usd), 0) AS cost FROM public.llm_usage "
            "WHERE agent_run_id = :r AND NOT blocked_by_budget"
        ),
        {"r": agent_run_id},
    ).one()
    return int(row.tokens), Decimal(row.cost)


def cost_last_24h(db: Session) -> Decimal:
    row = db.execute(
        text(
            "SELECT COALESCE(SUM(estimated_cost_usd), 0) AS cost FROM public.llm_usage "
            "WHERE created_at > now() - interval '24 hours' AND NOT blocked_by_budget"
        )
    ).one()
    return Decimal(row.cost)


def insert_usage(
    db: Session,
    *,
    project_id: uuid.UUID | None,
    run_id: uuid.UUID | None,
    requested_by: uuid.UUID | None,
    agent_run_id: uuid.UUID | None,
    purpose: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    blocked: bool,
    outcome: str,
    prompt_hash: str,
    template_version: str,
) -> int:
    row = db.execute(
        text(
            "INSERT INTO public.llm_usage (project_id, run_id, requested_by, agent_run_id, "
            "purpose, provider, model, input_tokens, output_tokens, estimated_cost_usd, "
            "blocked_by_budget, outcome, attempts, prompt_hash, template_version) VALUES "
            "(:p, :run, :u, :ar, :purpose, 'gemini', :model, :it, :ot, :cost, :blocked, "
            ":outcome, 0, :ph, :tv) RETURNING id"
        ),
        {
            "p": project_id,
            "run": run_id,
            "u": requested_by,
            "ar": agent_run_id,
            "purpose": purpose,
            "model": model,
            "it": input_tokens,
            "ot": output_tokens,
            "cost": cost_usd,
            "blocked": blocked,
            "outcome": outcome,
            "ph": prompt_hash,
            "tv": template_version,
        },
    ).one()
    return int(row.id)


def finalize_usage(
    db: Session,
    usage_id: int,
    *,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    outcome: str,
    latency_ms: int,
    attempts: int,
) -> None:
    db.execute(
        text(
            "UPDATE public.llm_usage SET input_tokens = :it, output_tokens = :ot, "
            "estimated_cost_usd = :cost, outcome = :outcome, latency_ms = :lat, "
            "attempts = :att WHERE id = :id"
        ),
        {
            "it": input_tokens,
            "ot": output_tokens,
            "cost": cost_usd,
            "outcome": outcome,
            "lat": latency_ms,
            "att": attempts,
            "id": usage_id,
        },
    )
