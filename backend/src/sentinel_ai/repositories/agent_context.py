"""Read-only lookups the agent workflows use, always scoped by project (an id alone is never
enough to reach another project's rows)."""

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from sentinel_ai.repositories.runs import ResultRecord

_RESULT_COLS = (
    "r.id, r.run_id, r.batch_id, r.planned_test_id, r.attempt, r.status, r.summary, "
    "r.exit_code, r.duration_ms, r.started_at, r.finished_at, r.created_at"
)


@dataclass(frozen=True)
class ScopedResult:
    result: ResultRecord
    check_id: str | None
    test_name: str


def get_result_scoped(
    db: Session, project_id: uuid.UUID, result_id: uuid.UUID
) -> ScopedResult | None:
    row = db.execute(
        text(
            f"SELECT {_RESULT_COLS}, pt.name AS test_name, pt.definition->>'check_id' AS check_id "
            "FROM public.test_results r JOIN public.test_runs tr ON tr.id = r.run_id "
            "JOIN public.planned_tests pt ON pt.id = r.planned_test_id "
            "WHERE r.id = :i AND tr.project_id = :p"
        ),
        {"i": result_id, "p": project_id},
    ).first()
    if row is None:
        return None
    data = dict(row._mapping)
    name, check = data.pop("test_name"), data.pop("check_id")
    return ScopedResult(ResultRecord(**data), check, name)


def run_in_project(db: Session, project_id: uuid.UUID, run_id: uuid.UUID) -> str | None:
    """Status of a run if it belongs to the project."""
    row = db.execute(
        text("SELECT status FROM public.test_runs WHERE id = :r AND project_id = :p"),
        {"r": run_id, "p": project_id},
    ).first()
    return str(row.status) if row else None


def result_for_check(db: Session, run_id: uuid.UUID, check_id: str) -> str | None:
    """Status of the (latest attempt of the) result for a catalog check in a run."""
    row = db.execute(
        text(
            "SELECT r.status FROM public.test_results r "
            "JOIN public.planned_tests pt ON pt.id = r.planned_test_id "
            "WHERE r.run_id = :r AND pt.definition->>'check_id' = :c "
            "ORDER BY r.attempt DESC, r.created_at DESC LIMIT 1"
        ),
        {"r": run_id, "c": check_id},
    ).first()
    return str(row.status) if row else None
