"""app_user schema: accounts, roles, sessions, password reset tokens.

Revision ID: 0001_app_user_schema
Revises:
"""

from alembic import op

revision = "0001_app_user_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Fails loudly (does not overwrite) if any of these objects already exist,
    # except the schema itself, which may pre-exist and is left untouched.
    op.execute("CREATE SCHEMA IF NOT EXISTS app_user")

    op.execute(
        """
        CREATE FUNCTION public.set_updated_at() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END $$
        """
    )

    op.execute(
        """
        CREATE TABLE app_user.roles (
            name        text PRIMARY KEY
                        CHECK (name IN ('developer', 'admin', 'super_admin')),
            rank        smallint NOT NULL UNIQUE,
            description text NOT NULL
        )
        """
    )
    op.execute(
        """
        INSERT INTO app_user.roles (name, rank, description) VALUES
          ('developer', 10, 'Works on authorized projects within policy'),
          ('admin', 20, 'Manages users, project access, and approvals within scope'),
          ('super_admin', 30, 'Platform-wide policy and privileged administration')
        """
    )

    op.execute(
        """
        CREATE TABLE app_user.users (
            id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            email               text NOT NULL
                                CHECK (email = lower(email) AND position('@' IN email) > 1),
            display_name        text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 200),
            password_hash       text NOT NULL,
            role_name           text NOT NULL DEFAULT 'developer'
                                REFERENCES app_user.roles (name),
            is_active           boolean NOT NULL DEFAULT true,
            failed_login_count  integer NOT NULL DEFAULT 0 CHECK (failed_login_count >= 0),
            locked_until        timestamptz,
            password_changed_at timestamptz NOT NULL DEFAULT now(),
            last_login_at       timestamptz,
            deactivated_at      timestamptz,
            created_at          timestamptz NOT NULL DEFAULT now(),
            updated_at          timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT users_email_key UNIQUE (email),
            CONSTRAINT users_deactivation_consistent
                CHECK (is_active OR deactivated_at IS NOT NULL)
        )
        """
    )
    op.execute("CREATE INDEX users_role_name_idx ON app_user.users (role_name)")
    op.execute(
        "CREATE TRIGGER users_set_updated_at BEFORE UPDATE ON app_user.users "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )

    # Server-side sessions. Only a keyed hash of the opaque token is stored.
    op.execute(
        """
        CREATE TABLE app_user.sessions (
            id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id             uuid NOT NULL REFERENCES app_user.users (id) ON DELETE CASCADE,
            token_hash          bytea NOT NULL UNIQUE CHECK (octet_length(token_hash) = 32),
            csrf_token_hash     bytea NOT NULL CHECK (octet_length(csrf_token_hash) = 32),
            created_at          timestamptz NOT NULL DEFAULT now(),
            last_seen_at        timestamptz NOT NULL DEFAULT now(),
            idle_expires_at     timestamptz NOT NULL,
            absolute_expires_at timestamptz NOT NULL,
            revoked_at          timestamptz,
            revoked_reason      text,
            ip_address          inet,
            user_agent          text CHECK (length(user_agent) <= 512),
            CONSTRAINT sessions_expiry_order CHECK (absolute_expires_at > created_at)
        )
        """
    )
    op.execute(
        "CREATE INDEX sessions_user_active_idx ON app_user.sessions (user_id) "
        "WHERE revoked_at IS NULL"
    )
    op.execute("CREATE INDEX sessions_idle_expires_idx ON app_user.sessions (idle_expires_at)")

    op.execute(
        """
        CREATE TABLE app_user.password_reset_tokens (
            id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id      uuid NOT NULL REFERENCES app_user.users (id) ON DELETE CASCADE,
            token_hash   bytea NOT NULL UNIQUE CHECK (octet_length(token_hash) = 32),
            created_at   timestamptz NOT NULL DEFAULT now(),
            expires_at   timestamptz NOT NULL,
            used_at      timestamptz,
            requested_ip inet,
            CONSTRAINT prt_expiry_order CHECK (expires_at > created_at)
        )
        """
    )
    op.execute("CREATE INDEX prt_user_idx ON app_user.password_reset_tokens (user_id)")


def downgrade() -> None:
    # No CASCADE anywhere: this removes only objects created above and fails
    # rather than dropping anything else that lives in the app_user schema.
    op.execute("DROP TABLE app_user.password_reset_tokens")
    op.execute("DROP TABLE app_user.sessions")
    op.execute("DROP TABLE app_user.users")
    op.execute("DROP TABLE app_user.roles")
    op.execute("DROP FUNCTION public.set_updated_at()")
    # Drop the schema only if nothing else lives in it.
    op.execute(
        """
        DO $$
        BEGIN
            DROP SCHEMA app_user;
        EXCEPTION WHEN dependent_objects_still_exist THEN
            RAISE NOTICE 'app_user schema not empty; left in place';
        END $$
        """
    )
