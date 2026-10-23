"""Stage 6: plan content binding, frozen plans, authorization justification.

Revision ID: 0003_plan_integrity
Revises: 0002_public_application_schema

Additive only (no data is rewritten or dropped):
  * test_plans: content_sha256, policy_snapshot, submitted_by/at. An approval is bound to
    the exact plan content that was reviewed (the hash), and a plan that is no longer a
    draft cannot change.
  * target_authorizations.justification: the requester's written reason.
  * approvals: a decision, once made, is final; high/critical risk cannot be self-approved.
  * triggers: planned tests of a non-draft plan are immutable except for their status, and
    plan status moves only along documented edges;
  * test_runs may only reference an approved plan of the same project, so every run is tied to
    the exact, hash-bound plan snapshot that was approved.
"""

from alembic import op

revision = "0003_plan_integrity"
down_revision = "0002_public_application_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE public.test_plans
            ADD COLUMN content_sha256 char(64) CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
            ADD COLUMN policy_snapshot jsonb,
            ADD COLUMN submitted_by uuid REFERENCES app_user.users (id),
            ADD COLUMN submitted_at timestamptz,
            ADD CONSTRAINT test_plans_policy_snapshot_is_object
                CHECK (policy_snapshot IS NULL OR jsonb_typeof(policy_snapshot) = 'object'),
            ADD CONSTRAINT test_plans_frozen_is_bound CHECK (
                status IN ('draft', 'rejected', 'superseded')
                OR (content_sha256 IS NOT NULL AND policy_snapshot IS NOT NULL
                    AND submitted_by IS NOT NULL AND submitted_at IS NOT NULL)
            )
        """
    )
    op.execute(
        """
        ALTER TABLE public.target_authorizations
            ADD COLUMN justification text
                CHECK (justification IS NULL OR length(justification) BETWEEN 10 AND 2000)
        """
    )
    op.execute(
        """
        ALTER TABLE public.approvals
            ADD CONSTRAINT approvals_no_self_approval_high_risk CHECK (
                decided_by IS NULL OR risk_level IN ('low', 'medium')
                OR decision <> 'approved' OR decided_by <> requested_by
            )
        """
    )

    op.execute(
        """
        CREATE FUNCTION public.approvals_decision_is_final() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.decision <> 'pending' THEN
                RAISE EXCEPTION 'approval decision is final' USING ERRCODE = '23514';
            END IF;
            IF NEW.plan_id IS DISTINCT FROM OLD.plan_id
               OR NEW.planned_test_id IS DISTINCT FROM OLD.planned_test_id
               OR NEW.authorization_id IS DISTINCT FROM OLD.authorization_id
               OR NEW.requested_by IS DISTINCT FROM OLD.requested_by
               OR NEW.risk_level IS DISTINCT FROM OLD.risk_level THEN
                RAISE EXCEPTION 'approval subject is immutable' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER approvals_final BEFORE UPDATE ON public.approvals "
        "FOR EACH ROW EXECUTE FUNCTION public.approvals_decision_is_final()"
    )

    op.execute(
        """
        CREATE FUNCTION public.test_plans_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.status <> 'draft' AND (
                   NEW.project_id IS DISTINCT FROM OLD.project_id
                OR NEW.snapshot_id IS DISTINCT FROM OLD.snapshot_id
                OR NEW.version IS DISTINCT FROM OLD.version
                OR NEW.plan_mode IS DISTINCT FROM OLD.plan_mode
                OR NEW.prompt IS DISTINCT FROM OLD.prompt
                OR NEW.risk_level IS DISTINCT FROM OLD.risk_level
                OR NEW.summary IS DISTINCT FROM OLD.summary
                OR NEW.created_by IS DISTINCT FROM OLD.created_by
                OR NEW.content_sha256 IS DISTINCT FROM OLD.content_sha256
                OR NEW.policy_snapshot IS DISTINCT FROM OLD.policy_snapshot
                OR NEW.submitted_by IS DISTINCT FROM OLD.submitted_by
                OR NEW.submitted_at IS DISTINCT FROM OLD.submitted_at
            ) THEN
                RAISE EXCEPTION 'a submitted test plan is immutable' USING ERRCODE = '23514';
            END IF;
            IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
                (OLD.status = 'draft' AND NEW.status IN ('pending_approval', 'approved', 'superseded'))
                OR (OLD.status = 'pending_approval'
                    AND NEW.status IN ('approved', 'rejected', 'superseded'))
                OR (OLD.status IN ('approved', 'rejected') AND NEW.status = 'superseded')
            ) THEN
                RAISE EXCEPTION 'invalid test plan transition: % -> %', OLD.status, NEW.status
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER test_plans_guard_trg BEFORE UPDATE ON public.test_plans "
        "FOR EACH ROW EXECUTE FUNCTION public.test_plans_guard()"
    )

    op.execute(
        """
        CREATE FUNCTION public.planned_tests_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            plan_status text;
            target_plan uuid;
        BEGIN
            target_plan := CASE WHEN TG_OP = 'DELETE' THEN OLD.plan_id ELSE NEW.plan_id END;
            SELECT status INTO plan_status FROM public.test_plans WHERE id = target_plan;
            -- No parent row (cascade delete of the plan itself) or a draft: free to change.
            IF plan_status IS NULL OR plan_status = 'draft' THEN
                RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
            END IF;
            IF TG_OP = 'UPDATE'
               AND NEW.id = OLD.id AND NEW.plan_id = OLD.plan_id AND NEW.ordinal = OLD.ordinal
               AND NEW.name = OLD.name AND NEW.category = OLD.category AND NEW.tool = OLD.tool
               AND NEW.origin = OLD.origin AND NEW.definition = OLD.definition
               AND NEW.script_artifact_id IS NOT DISTINCT FROM OLD.script_artifact_id
               AND NEW.risk_level = OLD.risk_level
               AND NEW.requires_approval = OLD.requires_approval
               AND NEW.rationale IS NOT DISTINCT FROM OLD.rationale THEN
                RETURN NEW;  -- only the execution status may change
            END IF;
            RAISE EXCEPTION 'planned tests of a submitted plan are immutable'
                USING ERRCODE = '23514';
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER planned_tests_guard_trg BEFORE INSERT OR UPDATE OR DELETE "
        "ON public.planned_tests FOR EACH ROW EXECUTE FUNCTION public.planned_tests_guard()"
    )
    op.execute(
        """
        CREATE FUNCTION public.test_runs_require_approved_plan() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM public.test_plans
                WHERE id = NEW.plan_id AND project_id = NEW.project_id AND status = 'approved'
            ) THEN
                RAISE EXCEPTION 'a run needs an approved plan of the same project'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER test_runs_plan_guard BEFORE INSERT ON public.test_runs "
        "FOR EACH ROW EXECUTE FUNCTION public.test_runs_require_approved_plan()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER test_runs_plan_guard ON public.test_runs")
    op.execute("DROP FUNCTION public.test_runs_require_approved_plan()")
    op.execute("DROP TRIGGER planned_tests_guard_trg ON public.planned_tests")
    op.execute("DROP FUNCTION public.planned_tests_guard()")
    op.execute("DROP TRIGGER test_plans_guard_trg ON public.test_plans")
    op.execute("DROP FUNCTION public.test_plans_guard()")
    op.execute("DROP TRIGGER approvals_final ON public.approvals")
    op.execute("DROP FUNCTION public.approvals_decision_is_final()")
    op.execute("ALTER TABLE public.approvals DROP CONSTRAINT approvals_no_self_approval_high_risk")
    op.execute("ALTER TABLE public.target_authorizations DROP COLUMN justification")
    op.execute(
        """
        ALTER TABLE public.test_plans
            DROP CONSTRAINT test_plans_frozen_is_bound,
            DROP CONSTRAINT test_plans_policy_snapshot_is_object,
            DROP COLUMN submitted_at,
            DROP COLUMN submitted_by,
            DROP COLUMN policy_snapshot,
            DROP COLUMN content_sha256
        """
    )
