"""Stage 12 completion: trace ids, event de-duplication and cost/resource alert rules (ADR-0011).

Revision ID: 0011_trace_dedup_cost_alerts
Revises: 0010_observability_alerts

``test_runs.trace_id`` and ``agent_runs.trace_id`` give every platform workflow a W3C-format
trace id (32 lowercase hex characters) so events a target application reports with the same
trace id can be correlated with the run or assistant workflow (existing rows receive one too).
``ingest_event_ids`` remembers the optional ``event_id`` of accepted events for 24 hours so a
retried request is not counted twice. The ``alerts`` rule vocabulary gains the deterministic
cost and resource rules. ``events`` gets an index for "other events in the same trace".

Additive apart from the widened CHECK; nothing is rewritten except that adding the two trace
columns with a volatile default rewrites ``test_runs`` and ``agent_runs`` once (small tables).
"""

from alembic import op

revision = "0011_trace_dedup_cost_alerts"
down_revision = "0010_observability_alerts"
branch_labels = None
depends_on = None

OLD_RULES = (
    "('new_error_group', 'error_rate_spike', 'run_failed', 'finding_reopened', "
    "'telemetry_gap', 'ingest_dropping', 'alert_overflow')"
)
NEW_RULES = (
    "('new_error_group', 'error_rate_spike', 'run_failed', 'finding_reopened', "
    "'telemetry_gap', 'ingest_dropping', 'alert_overflow', 'llm_cost_spike', 'llm_runaway', "
    "'llm_error_rate', 'run_duration_anomaly')"
)
TRACE_DEFAULT = "replace(gen_random_uuid()::text, '-', '')"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE public.test_runs ADD COLUMN trace_id text "
        f"NOT NULL DEFAULT {TRACE_DEFAULT} CONSTRAINT test_runs_trace_id_check "
        "CHECK (trace_id ~ '^[0-9a-f]{32}$')"
    )
    op.execute("CREATE INDEX test_runs_trace_idx ON public.test_runs (project_id, trace_id)")
    op.execute(
        "ALTER TABLE public.agent_runs ADD COLUMN trace_id text "
        f"NOT NULL DEFAULT {TRACE_DEFAULT} CONSTRAINT agent_runs_trace_id_check "
        "CHECK (trace_id ~ '^[0-9a-f]{32}$')"
    )
    op.execute("CREATE INDEX agent_runs_trace_idx ON public.agent_runs (project_id, trace_id)")
    op.execute(
        "CREATE INDEX events_trace_idx ON public.events (project_id, trace_id) "
        "WHERE trace_id IS NOT NULL"
    )
    op.execute(
        """
        CREATE TABLE public.ingest_event_ids (
            project_id  uuid NOT NULL REFERENCES public.projects (id) ON DELETE CASCADE,
            event_id    uuid NOT NULL,
            received_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (project_id, event_id)
        )
        """
    )
    op.execute("CREATE INDEX ingest_event_ids_age_idx ON public.ingest_event_ids (received_at)")
    op.execute("ALTER TABLE public.alerts DROP CONSTRAINT alerts_rule_check")
    op.execute(
        f"ALTER TABLE public.alerts ADD CONSTRAINT alerts_rule_check CHECK (rule IN {NEW_RULES})"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM public.alerts WHERE rule IN "
        "('llm_cost_spike', 'llm_runaway', 'llm_error_rate', 'run_duration_anomaly')"
    )
    op.execute("ALTER TABLE public.alerts DROP CONSTRAINT alerts_rule_check")
    op.execute(
        f"ALTER TABLE public.alerts ADD CONSTRAINT alerts_rule_check CHECK (rule IN {OLD_RULES})"
    )
    op.execute("DROP TABLE public.ingest_event_ids")
    op.execute("DROP INDEX public.events_trace_idx")
    op.execute("DROP INDEX public.agent_runs_trace_idx")
    op.execute("ALTER TABLE public.agent_runs DROP COLUMN trace_id")
    op.execute("DROP INDEX public.test_runs_trace_idx")
    op.execute("ALTER TABLE public.test_runs DROP COLUMN trace_id")
