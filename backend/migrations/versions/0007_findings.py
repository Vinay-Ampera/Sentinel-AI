"""Stage 10: scanner findings carry confidence, location, limitations and their source.

Revision ID: 0007_findings
Revises: 0006_test_cases

The ``findings`` family (findings, finding_events, finding_evidence, verification_attempts)
already exists from 0002. This adds what a scanner finding needs to be reviewed honestly:

  * ``confidence`` (the tool's own confidence, kept apart from ``severity``);
  * ``rule_id``, ``file_path``, ``line_number`` (where the tool pointed) and ``source_id``
    (the project source that was scanned, so a later scan of the same source can tell whether
    a finding is gone);
  * ``limitations`` (plain text shown with the finding) and ``occurrences``;
  * ``verification_attempts.method`` (``rescan`` = automatic, ``manual`` = a person) and
    ``evidence_artifact_id`` (the report that backs an attempt).

All columns are nullable or defaulted, so existing rows stay valid. A finding is never
``confirmed`` by this migration or by ingestion; the 0002 trigger still requires evidence.
"""

from alembic import op

revision = "0007_findings"
down_revision = "0006_test_cases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE public.findings
            ADD COLUMN confidence  text NOT NULL DEFAULT 'low'
                CONSTRAINT findings_confidence_check CHECK (confidence IN ('low', 'medium', 'high')),
            ADD COLUMN rule_id     text CHECK (rule_id IS NULL OR length(rule_id) <= 100),
            ADD COLUMN file_path   text CHECK (file_path IS NULL OR length(file_path) <= 400),
            ADD COLUMN line_number integer CHECK (line_number IS NULL OR line_number > 0),
            ADD COLUMN source_id   uuid REFERENCES public.project_sources (id),
            ADD COLUMN limitations text CHECK (limitations IS NULL OR length(limitations) <= 2000),
            ADD COLUMN occurrences integer NOT NULL DEFAULT 1 CHECK (occurrences >= 1)
        """
    )
    op.execute("CREATE INDEX findings_source_idx ON public.findings (project_id, source_id)")
    op.execute(
        """
        ALTER TABLE public.verification_attempts
            ADD COLUMN method text NOT NULL DEFAULT 'manual'
                CONSTRAINT verification_attempts_method_check CHECK (method IN ('rescan', 'manual')),
            ADD COLUMN evidence_artifact_id uuid REFERENCES public.artifacts (id)
        """
    )
    op.execute(
        "ALTER TABLE public.finding_events DROP CONSTRAINT IF EXISTS finding_events_event_type_check"
    )
    op.execute(
        "ALTER TABLE public.finding_events ADD CONSTRAINT finding_events_event_type_check "
        "CHECK (event_type IN ('created','status_changed','verification_changed','assigned',"
        "'evidence_added','comment','seen_again','reopened','verification_attempt'))"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM public.finding_events WHERE event_type IN ('reopened','verification_attempt')"
    )
    op.execute(
        "ALTER TABLE public.finding_events DROP CONSTRAINT IF EXISTS finding_events_event_type_check"
    )
    op.execute(
        "ALTER TABLE public.finding_events ADD CONSTRAINT finding_events_event_type_check "
        "CHECK (event_type IN ('created','status_changed','verification_changed','assigned',"
        "'evidence_added','comment','seen_again'))"
    )
    op.execute(
        "ALTER TABLE public.verification_attempts DROP COLUMN evidence_artifact_id, DROP COLUMN method"
    )
    op.execute("DROP INDEX IF EXISTS public.findings_source_idx")
    op.execute(
        "ALTER TABLE public.findings DROP COLUMN occurrences, DROP COLUMN limitations, "
        "DROP COLUMN source_id, DROP COLUMN line_number, DROP COLUMN file_path, "
        "DROP COLUMN rule_id, DROP COLUMN confidence"
    )
