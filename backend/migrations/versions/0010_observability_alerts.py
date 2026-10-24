"""Stage 12: observability ingestion, alerts and the failure-to-test link (ADR-0011).

Revision ID: 0010_observability_alerts
Revises: 0009_llm_gateway_agent_runs

``ingest_keys``: project-scoped, write-only credentials for pushing events (only a keyed hash is
stored). ``event_groups`` / ``event_buckets`` / ``events``: de-duplicated groups, hourly counts
and a capped number of redacted samples (never a raw stream, never a raw payload).
``ingest_stats``: per project and day, accepted events, dropped events by reason and rule
evaluation errors (the basis of the telemetry disclosure and the daily quota). ``alerts`` and the
append-only ``alert_history``: one open alert per (project, rule, subject) by a partial unique
index. ``regression_tests`` gains ``alert_id`` and ``event_group_id`` (a proposal may be drafted
from an alert); both are frozen with the rest of the draft and are plain restrictive foreign
keys, so retention never deletes an alert or group a proposal points to.

Every table carries ``project_id``; nothing here stores a secret, a raw payload or a prompt.
"""

from alembic import op

revision = "0010_observability_alerts"
down_revision = "0009_llm_gateway_agent_runs"
branch_labels = None
depends_on = None

USERS = "app_user.users (id)"
RULES = (
    "('new_error_group', 'error_rate_spike', 'run_failed', 'finding_reopened', "
    "'telemetry_gap', 'ingest_dropping', 'alert_overflow')"
)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE public.ingest_keys (
            id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id   uuid NOT NULL REFERENCES public.projects (id) ON DELETE CASCADE,
            key_id       text NOT NULL CHECK (key_id ~ '^[0-9a-f]{{12}}$'),
            key_hash     bytea NOT NULL CHECK (octet_length(key_hash) = 32),
            label        text NOT NULL CHECK (length(label) BETWEEN 1 AND 80),
            created_by   uuid REFERENCES {USERS},
            created_at   timestamptz NOT NULL DEFAULT now(),
            expires_at   timestamptz NOT NULL,
            revoked_at   timestamptz,
            last_used_at timestamptz,
            CONSTRAINT ingest_keys_expiry CHECK (expires_at > created_at)
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX ingest_keys_key_id ON public.ingest_keys (key_id)")
    op.execute(
        "CREATE INDEX ingest_keys_project_idx ON public.ingest_keys (project_id, created_at DESC)"
    )

    op.execute(
        """
        CREATE TABLE public.event_groups (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id    uuid NOT NULL REFERENCES public.projects (id) ON DELETE CASCADE,
            fingerprint   text NOT NULL CHECK (length(fingerprint) = 64),
            fp_version    text NOT NULL CHECK (length(fp_version) BETWEEN 1 AND 20),
            service       text NOT NULL CHECK (length(service) BETWEEN 1 AND 64),
            environment   text NOT NULL CONSTRAINT event_groups_environment_check
                          CHECK (environment IN ('local', 'development', 'staging', 'production', 'unknown')),
            level_class   text NOT NULL CHECK (level_class IN ('warning', 'error', 'fatal')),
            error_type    text CHECK (error_type IS NULL OR length(error_type) <= 128),
            message_norm  text NOT NULL CHECK (length(message_norm) <= 512),
            first_seen    timestamptz NOT NULL DEFAULT now(),
            last_seen     timestamptz NOT NULL DEFAULT now(),
            total_count   bigint NOT NULL DEFAULT 1 CHECK (total_count >= 1),
            has_stack     boolean NOT NULL DEFAULT false,
            is_overflow   boolean NOT NULL DEFAULT false,
            CONSTRAINT event_groups_seen_order CHECK (last_seen >= first_seen)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX event_groups_fingerprint ON public.event_groups "
        "(project_id, fingerprint)"
    )
    op.execute(
        "CREATE INDEX event_groups_project_seen_idx ON public.event_groups "
        "(project_id, last_seen DESC)"
    )

    op.execute(
        """
        CREATE TABLE public.event_buckets (
            group_id     uuid NOT NULL REFERENCES public.event_groups (id) ON DELETE CASCADE,
            bucket_start timestamptz NOT NULL,
            count        integer NOT NULL CHECK (count >= 1),
            PRIMARY KEY (group_id, bucket_start)
        )
        """
    )
    op.execute("CREATE INDEX event_buckets_start_idx ON public.event_buckets (bucket_start)")

    op.execute(
        """
        CREATE TABLE public.events (
            id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            seq                bigint GENERATED ALWAYS AS IDENTITY,
            project_id         uuid NOT NULL REFERENCES public.projects (id) ON DELETE CASCADE,
            group_id           uuid NOT NULL REFERENCES public.event_groups (id) ON DELETE CASCADE,
            key_id             uuid REFERENCES public.ingest_keys (id) ON DELETE SET NULL,
            event_id           uuid,
            received_at        timestamptz NOT NULL DEFAULT now(),
            client_timestamp   timestamptz,
            timestamp_untrusted boolean NOT NULL DEFAULT false,
            level              text NOT NULL CHECK (level IN ('warning', 'error', 'fatal')),
            service            text NOT NULL CHECK (length(service) BETWEEN 1 AND 64),
            environment        text NOT NULL CHECK (environment IN ('local', 'development', 'staging', 'production', 'unknown')),
            message            text NOT NULL CHECK (length(message) <= 2048),
            error_type         text CHECK (error_type IS NULL OR length(error_type) <= 128),
            stack              text CHECK (stack IS NULL OR length(stack) <= 8192),
            attributes         jsonb NOT NULL DEFAULT '{}'::jsonb,
            trace_id           text CHECK (trace_id IS NULL OR trace_id ~ '^[0-9a-f]{32}$'),
            span_id            text CHECK (span_id IS NULL OR span_id ~ '^[0-9a-f]{16}$'),
            release            text CHECK (release IS NULL OR length(release) <= 64),
            claimed            jsonb NOT NULL DEFAULT '{}'::jsonb,
            correlation        jsonb NOT NULL DEFAULT '{}'::jsonb,
            redactions         jsonb NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    op.execute("CREATE INDEX events_group_idx ON public.events (group_id, received_at, seq)")
    op.execute("CREATE INDEX events_received_idx ON public.events (received_at)")

    op.execute(
        """
        CREATE TABLE public.ingest_stats (
            project_id  uuid NOT NULL REFERENCES public.projects (id) ON DELETE CASCADE,
            day         date NOT NULL,
            accepted    integer NOT NULL DEFAULT 0 CHECK (accepted >= 0),
            dropped     jsonb NOT NULL DEFAULT '{}'::jsonb,
            eval_errors integer NOT NULL DEFAULT 0 CHECK (eval_errors >= 0),
            PRIMARY KEY (project_id, day)
        )
        """
    )

    op.execute(
        f"""
        CREATE TABLE public.alerts (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id    uuid NOT NULL REFERENCES public.projects (id) ON DELETE CASCADE,
            rule          text NOT NULL CONSTRAINT alerts_rule_check CHECK (rule IN {RULES}),
            rule_version  text NOT NULL CHECK (length(rule_version) BETWEEN 1 AND 20),
            subject_key   text NOT NULL CHECK (length(subject_key) BETWEEN 1 AND 200),
            group_id      uuid REFERENCES public.event_groups (id),
            run_id        uuid REFERENCES public.test_runs (id) ON DELETE SET NULL,
            result_id     uuid REFERENCES public.test_results (id) ON DELETE SET NULL,
            finding_id    uuid REFERENCES public.findings (id) ON DELETE SET NULL,
            severity      text NOT NULL CHECK (severity IN ('info', 'low', 'medium', 'high')),
            status        text NOT NULL DEFAULT 'open' CONSTRAINT alerts_status_check
                          CHECK (status IN ('open', 'acknowledged', 'resolved')),
            title         text NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
            measured      jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            evidence      jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            next_action   text NOT NULL CHECK (length(next_action) BETWEEN 1 AND 400),
            occurrences   integer NOT NULL DEFAULT 1 CHECK (occurrences >= 1),
            cause_status  text NOT NULL DEFAULT 'not_investigated'
                          CHECK (cause_status IN ('not_investigated', 'investigated')),
            agent_run_id  uuid REFERENCES public.agent_runs (id) ON DELETE SET NULL,
            first_seen    timestamptz NOT NULL DEFAULT now(),
            last_seen     timestamptz NOT NULL DEFAULT now(),
            closed_at     timestamptz,
            created_at    timestamptz NOT NULL DEFAULT now(),
            updated_at    timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT alerts_closed_consistent CHECK ((status = 'resolved') = (closed_at IS NOT NULL))
        )
        """
    )
    # One open (open or acknowledged) alert per project, rule and subject.
    op.execute(
        "CREATE UNIQUE INDEX alerts_one_open ON public.alerts (project_id, rule, subject_key) "
        "WHERE status <> 'resolved'"
    )
    op.execute("CREATE INDEX alerts_project_idx ON public.alerts (project_id, last_seen DESC)")
    op.execute(
        "CREATE INDEX alerts_group_idx ON public.alerts (group_id) WHERE group_id IS NOT NULL"
    )
    op.execute(
        "CREATE TRIGGER alerts_set_updated_at BEFORE UPDATE ON public.alerts "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )

    op.execute(
        f"""
        CREATE TABLE public.alert_history (
            id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            alert_id      uuid NOT NULL REFERENCES public.alerts (id) ON DELETE CASCADE,
            project_id    uuid NOT NULL REFERENCES public.projects (id) ON DELETE CASCADE,
            action        text NOT NULL CHECK (action IN ('created', 'acknowledged', 'resolved', 'reopened', 'investigated')),
            actor_user_id uuid REFERENCES {USERS},
            note          text CHECK (note IS NULL OR length(note) <= 1000),
            detail        jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            created_at    timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX alert_history_alert_idx ON public.alert_history (alert_id, id)")
    op.execute(
        "CREATE TRIGGER alert_history_append_only BEFORE UPDATE ON public.alert_history "
        "FOR EACH ROW EXECUTE FUNCTION public.forbid_mutation()"
    )

    # A regression proposal may now come from an alert (and its event group).
    op.execute(
        """
        ALTER TABLE public.regression_tests
            ADD COLUMN alert_id        uuid REFERENCES public.alerts (id),
            ADD COLUMN event_group_id  uuid REFERENCES public.event_groups (id),
            DROP CONSTRAINT regression_tests_subject,
            ADD CONSTRAINT regression_tests_subject
                CHECK (finding_id IS NOT NULL OR result_id IS NOT NULL OR alert_id IS NOT NULL)
        """
    )
    op.execute(
        "CREATE INDEX regression_tests_alert_idx ON public.regression_tests (alert_id) "
        "WHERE alert_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX regression_tests_group_idx ON public.regression_tests (event_group_id) "
        "WHERE event_group_id IS NOT NULL"
    )
    op.execute(_guard(with_alert=True))


def _guard(*, with_alert: bool) -> str:
    extra = (
        "               OR NEW.alert_id IS DISTINCT FROM OLD.alert_id\n"
        "               OR NEW.event_group_id IS DISTINCT FROM OLD.event_group_id\n"
        if with_alert
        else ""
    )
    return f"""
        CREATE OR REPLACE FUNCTION public.regression_tests_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.project_id IS DISTINCT FROM OLD.project_id
               OR NEW.finding_id IS DISTINCT FROM OLD.finding_id
               OR NEW.result_id IS DISTINCT FROM OLD.result_id
{extra}               OR NEW.title IS DISTINCT FROM OLD.title
               OR NEW.rationale IS DISTINCT FROM OLD.rationale
               OR NEW.target_path IS DISTINCT FROM OLD.target_path
               OR NEW.framework IS DISTINCT FROM OLD.framework
               OR NEW.code IS DISTINCT FROM OLD.code
               OR NEW.expected_behavior IS DISTINCT FROM OLD.expected_behavior
               OR NEW.evidence_ids IS DISTINCT FROM OLD.evidence_ids
               OR NEW.risk_flags IS DISTINCT FROM OLD.risk_flags
               OR NEW.overlap IS DISTINCT FROM OLD.overlap THEN
                RAISE EXCEPTION 'a regression test proposal cannot be edited after it is stored'
                    USING ERRCODE = '23514';
            END IF;
            IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
                (OLD.status = 'proposed' AND NEW.status IN ('accepted', 'rejected'))
                OR (OLD.status = 'accepted' AND NEW.status = 'verified')) THEN
                RAISE EXCEPTION 'invalid regression test status change % -> %', OLD.status, NEW.status
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
        """


def downgrade() -> None:
    op.execute(_guard(with_alert=False))
    op.execute("DROP INDEX IF EXISTS public.regression_tests_group_idx")
    op.execute("DROP INDEX IF EXISTS public.regression_tests_alert_idx")
    # Proposals drafted from an alert have no other subject; the old shape cannot hold them.
    op.execute("DELETE FROM public.regression_tests WHERE finding_id IS NULL AND result_id IS NULL")
    op.execute(
        """
        ALTER TABLE public.regression_tests
            DROP CONSTRAINT regression_tests_subject,
            ADD CONSTRAINT regression_tests_subject
                CHECK (finding_id IS NOT NULL OR result_id IS NOT NULL),
            DROP COLUMN event_group_id,
            DROP COLUMN alert_id
        """
    )
    op.execute("DROP TABLE public.alert_history")
    op.execute("DROP TABLE public.alerts")
    op.execute("DROP TABLE public.ingest_stats")
    op.execute("DROP TABLE public.events")
    op.execute("DROP TABLE public.event_buckets")
    op.execute("DROP TABLE public.event_groups")
    op.execute("DROP TABLE public.ingest_keys")
