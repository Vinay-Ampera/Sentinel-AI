"""Stage 9: explicit "not run" result state and per-test-case results.

Revision ID: 0006_test_cases
Revises: 0005_job_queue

  * test_results.status gains ``not_run``: a planned test that never started (its batch was
    cancelled, timed out, failed to start or lost its worker). It was recorded as
    ``skipped``/``cancelled`` in Stage 7, which blurred "chosen not to run" with "never ran".
  * test_case_results: the individual cases a runner reported (for pytest, one row per test
    function) under the planned-test result that produced them. Capped column lengths keep an
    untrusted runner from storing unbounded text.

Additive except the widened CHECK; downgrade maps ``not_run`` back to ``skipped``.
"""

from alembic import op

revision = "0006_test_cases"
down_revision = "0005_job_queue"
branch_labels = None
depends_on = None

_OLD = (
    "passed",
    "failed",
    "error",
    "skipped",
    "blocked",
    "timed_out",
    "cancelled",
    "failed_to_start",
)
_NEW = (*_OLD, "not_run")


def _check(values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"CHECK (status IN ({quoted}))"


def upgrade() -> None:
    op.execute("ALTER TABLE public.test_results DROP CONSTRAINT test_results_status_check")
    op.execute(
        f"ALTER TABLE public.test_results ADD CONSTRAINT test_results_status_check {_check(_NEW)}"
    )
    op.execute(
        """
        CREATE TABLE public.test_case_results (
            id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            result_id   uuid NOT NULL REFERENCES public.test_results (id) ON DELETE CASCADE,
            run_id      uuid NOT NULL REFERENCES public.test_runs (id) ON DELETE CASCADE,
            ordinal     integer NOT NULL CHECK (ordinal >= 1),
            suite       text CHECK (length(suite) <= 500),
            classname   text CHECK (length(classname) <= 500),
            name        text NOT NULL CHECK (length(name) BETWEEN 1 AND 500),
            status      text NOT NULL CHECK (status IN ('passed', 'failed', 'error', 'skipped')),
            duration_ms bigint CHECK (duration_ms >= 0),
            message     text CHECK (length(message) <= 2000),
            detail      text CHECK (length(detail) <= 10000),
            created_at  timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT test_case_results_ordinal UNIQUE (result_id, ordinal)
        )
        """
    )
    op.execute(
        "CREATE INDEX test_case_results_run_idx ON public.test_case_results (run_id, status)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE public.test_case_results")
    op.execute("UPDATE public.test_results SET status = 'skipped' WHERE status = 'not_run'")
    op.execute("ALTER TABLE public.test_results DROP CONSTRAINT test_results_status_check")
    op.execute(
        f"ALTER TABLE public.test_results ADD CONSTRAINT test_results_status_check {_check(_OLD)}"
    )
