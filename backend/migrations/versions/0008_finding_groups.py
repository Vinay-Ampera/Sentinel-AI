"""Stage 10: normalized finding attributes and cross-scanner duplicate groups.

Revision ID: 0008_finding_groups
Revises: 0007_findings

Adds to ``findings``: ``cwe`` (the weakness class several tools can agree on), ``component``
(``pypi:name@1.2`` or ``GET https://host/path``, for dependency and dynamic findings),
``aliases`` (advisory/CVE ids that name the same issue) and ``group_id``.

``finding_groups`` links findings that several scanners (or several advisories) report for the
same underlying issue. Grouping never merges, hides or deletes a finding: each keeps its own
tool, evidence, status and verification state, and the group is derived data that the service
recomputes after every scan. ``group_id`` is set to NULL if a group row is removed.
All columns are nullable or defaulted, so existing rows stay valid.
"""

from alembic import op

revision = "0008_finding_groups"
down_revision = "0007_findings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE public.finding_groups (
            id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id  uuid NOT NULL REFERENCES public.projects (id) ON DELETE CASCADE,
            group_key   text NOT NULL CHECK (length(group_key) BETWEEN 8 AND 200),
            kind        text NOT NULL CONSTRAINT finding_groups_kind_check
                        CHECK (kind IN ('location', 'advisory')),
            created_at  timestamptz NOT NULL DEFAULT now(),
            updated_at  timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT finding_groups_project_key UNIQUE (project_id, group_key)
        )
        """
    )
    op.execute(
        """
        ALTER TABLE public.findings
            ADD COLUMN cwe       integer CHECK (cwe IS NULL OR cwe BETWEEN 1 AND 99999),
            ADD COLUMN component text CHECK (component IS NULL OR length(component) <= 400),
            ADD COLUMN aliases   text[] NOT NULL DEFAULT '{}'
                CHECK (cardinality(aliases) <= 20),
            ADD COLUMN group_id  uuid REFERENCES public.finding_groups (id) ON DELETE SET NULL
        """
    )
    op.execute("CREATE INDEX findings_group_idx ON public.findings (project_id, group_id)")
    op.execute(
        "CREATE INDEX findings_cwe_idx ON public.findings (project_id, cwe) WHERE cwe IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.findings_cwe_idx")
    op.execute("DROP INDEX IF EXISTS public.findings_group_idx")
    op.execute(
        "ALTER TABLE public.findings DROP COLUMN group_id, DROP COLUMN aliases, "
        "DROP COLUMN component, DROP COLUMN cwe"
    )
    op.execute("DROP TABLE public.finding_groups")
