"""Stage 6 follow-up: temporary, audited Super Admin break-glass project access.

Revision ID: 0004_break_glass
Revises: 0003_plan_integrity

Additive: one new table. A grant gives its Super Admin READ-ONLY access to one project for
at most four hours; it can be revoked early but never extended or edited otherwise. The
database enforces the shape (justification, bounded window, revoke consistency); the
application audits the grant, every use, and the revocation.
"""

from alembic import op

revision = "0004_break_glass"
down_revision = "0003_plan_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE public.break_glass_grants (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id    uuid NOT NULL REFERENCES public.projects (id) ON DELETE CASCADE,
            user_id       uuid NOT NULL REFERENCES app_user.users (id),
            justification text NOT NULL CHECK (length(justification) BETWEEN 20 AND 2000),
            created_at    timestamptz NOT NULL DEFAULT now(),
            expires_at    timestamptz NOT NULL,
            revoked_at    timestamptz,
            revoked_by    uuid REFERENCES app_user.users (id),
            CONSTRAINT break_glass_window
                CHECK (expires_at > created_at AND expires_at <= created_at + interval '4 hours'),
            CONSTRAINT break_glass_revoke_consistent
                CHECK ((revoked_at IS NULL) = (revoked_by IS NULL))
        )
        """
    )
    op.execute(
        "CREATE INDEX break_glass_project_idx ON public.break_glass_grants (project_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX break_glass_user_idx ON public.break_glass_grants (user_id, project_id) "
        "WHERE revoked_at IS NULL"
    )
    op.execute(
        """
        CREATE FUNCTION public.break_glass_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.project_id IS DISTINCT FROM OLD.project_id
               OR NEW.user_id IS DISTINCT FROM OLD.user_id
               OR NEW.justification IS DISTINCT FROM OLD.justification
               OR NEW.created_at IS DISTINCT FROM OLD.created_at
               OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
               OR (OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at) THEN
                RAISE EXCEPTION 'break-glass grants cannot be extended or edited'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER break_glass_guard BEFORE UPDATE ON public.break_glass_grants "
        "FOR EACH ROW EXECUTE FUNCTION public.break_glass_immutable()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER break_glass_guard ON public.break_glass_grants")
    op.execute("DROP FUNCTION public.break_glass_immutable()")
    op.execute("DROP TABLE public.break_glass_grants")
