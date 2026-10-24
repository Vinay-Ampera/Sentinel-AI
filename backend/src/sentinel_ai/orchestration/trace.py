"""Writes the step trace of an agent run (one durable row per graph node transition).

Each step is committed in its own short transaction, so the trace of a workflow survives a
failure or rollback in the request that ran it. Details must already be free of prompts,
model text and secrets: callers pass counts, ids and stable reason codes only."""

import uuid
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from sentinel_ai.repositories import agent_runs

KINDS = ("deterministic", "decision", "llm", "policy")


class Trace:
    def __init__(self, session_factory: sessionmaker[Session], run_id: uuid.UUID) -> None:
        self._sessions = session_factory
        self.run_id = run_id
        self.steps = 0

    def step(
        self,
        node: str,
        kind: str,
        outcome: str,
        detail: dict[str, Any] | None = None,
        *,
        usage_id: int | None = None,
    ) -> None:
        if kind not in KINDS:
            raise ValueError(f"unknown step kind {kind!r}")
        with self._sessions() as db:
            agent_runs.add_step(
                db, self.run_id, node=node, kind=kind, outcome=outcome, detail=detail or {},
                llm_usage_id=usage_id,
            )  # fmt: skip
            db.commit()
        self.steps += 1
