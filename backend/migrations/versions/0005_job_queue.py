"""Stage 7: job queue support (leases, heartbeat, batch membership).

Revision ID: 0005_job_queue
Revises: 0004_break_glass

Additive only. The run/batch state machine, its transition table and triggers, the
idempotency index and ``job_events`` already exist (migration 0002) and are not changed.

  * test_batches.heartbeat_at / lease_expires_at: a live worker renews the lease on every
    step; an expired lease is how the reconciler recognises a lost worker. While a batch is
    still ``queued`` the same lease column is the *enqueue* deadline (a dispatch whose
    message never reached a worker is re-dispatched after it).
  * test_batches.not_before: earliest time a re-queued (retried) batch may be claimed
    (exponential backoff with jitter).
  * test_batch_items: which planned tests belong to which batch. A planned test belongs to
    at most one batch of a run.
"""

from alembic import op

revision = "0005_job_queue"
down_revision = "0004_break_glass"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE public.test_batches
            ADD COLUMN heartbeat_at     timestamptz,
            ADD COLUMN lease_expires_at timestamptz,
            ADD COLUMN not_before       timestamptz
        """
    )
    op.execute(
        "CREATE INDEX test_batches_lease_idx ON public.test_batches (lease_expires_at) "
        "WHERE status IN ('queued', 'dispatched', 'running', 'cancel_requested')"
    )
    op.execute(
        """
        CREATE TABLE public.test_batch_items (
            batch_id        uuid NOT NULL REFERENCES public.test_batches (id) ON DELETE CASCADE,
            run_id          uuid NOT NULL REFERENCES public.test_runs (id) ON DELETE CASCADE,
            planned_test_id uuid NOT NULL REFERENCES public.planned_tests (id),
            ordinal         integer NOT NULL CHECK (ordinal >= 1),
            PRIMARY KEY (batch_id, planned_test_id),
            CONSTRAINT test_batch_items_batch_ordinal UNIQUE (batch_id, ordinal),
            CONSTRAINT test_batch_items_once_per_run UNIQUE (run_id, planned_test_id)
        )
        """
    )
    op.execute("CREATE INDEX test_batch_items_run_idx ON public.test_batch_items (run_id)")


def downgrade() -> None:
    op.execute("DROP TABLE public.test_batch_items")
    op.execute("DROP INDEX public.test_batches_lease_idx")
    op.execute(
        "ALTER TABLE public.test_batches DROP COLUMN not_before, "
        "DROP COLUMN lease_expires_at, DROP COLUMN heartbeat_at"
    )
