"""public schema: teams, projects, plans, runs, results, findings, artifacts, audit.

Revision ID: 0002_public_application_schema
Revises: 0001_app_user_schema
"""

from alembic import op

revision = "0002_public_application_schema"
down_revision = "0001_app_user_schema"
branch_labels = None
depends_on = None

USERS = "app_user.users (id)"

RISK = ("low", "medium", "high", "critical")
RUN_STATUSES = (
    "queued",
    "dispatched",
    "running",
    "cancel_requested",
    "completed",
    "failed",
    "cancelled",
    "timed_out",
    "blocked",
)
RESULT_STATUSES = (
    "passed",
    "failed",
    "error",
    "skipped",
    "blocked",
    "timed_out",
    "cancelled",
    "failed_to_start",
)
PLANNED_TEST_STATUSES = (
    "planned",
    "approved",
    "executed",
    "skipped",
    "blocked",
    "failed_to_start",
    "deferred",
)

# (entity, from_status, to_status). Mirrors docs/architecture/JOB_AND_SANDBOX_DESIGN.md.
_COMMON = [
    ("queued", "dispatched"),
    ("queued", "cancelled"),
    ("queued", "blocked"),
    ("queued", "timed_out"),
    ("dispatched", "running"),
    ("dispatched", "failed"),
    ("dispatched", "cancel_requested"),
    ("dispatched", "cancelled"),
    ("dispatched", "timed_out"),
    ("running", "completed"),
    ("running", "failed"),
    ("running", "cancel_requested"),
    ("running", "timed_out"),
    ("cancel_requested", "cancelled"),
    ("cancel_requested", "completed"),
    ("cancel_requested", "failed"),
    ("cancel_requested", "timed_out"),
    ("blocked", "queued"),
    ("blocked", "cancelled"),
]
# Batches may be retried (failed/timed_out -> queued) and re-queued after a worker
# loss (dispatched/running -> queued). Runs are never retried in place: a rerun is a
# new run row with parent_run_id set.
_BATCH_ONLY = [
    ("failed", "queued"),
    ("timed_out", "queued"),
    ("dispatched", "queued"),
    ("running", "queued"),
]


def _in(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"CHECK ({column} IN ({quoted}))"


def _transition_rows() -> str:
    rows = [("test_run", a, b) for a, b in _COMMON]
    rows += [("test_batch", a, b) for a, b in _COMMON + _BATCH_ONLY]
    return ", ".join(f"('{e}', '{a}', '{b}')" for e, a, b in rows)


UPDATED_AT_TABLES = (
    "teams",
    "projects",
    "project_sources",
    "target_authorizations",
    "test_plans",
    "planned_tests",
    "test_runs",
    "test_batches",
    "findings",
    "policies",
)

CREATED_TABLES = (
    # dependency order; downgrade drops in reverse
    "policies",
    "audit_events",
    "llm_usage",
    "regression_tests",
    "verification_attempts",
    "finding_evidence",
    "finding_events",
    "findings",
    "job_events",
    "test_results",
    "test_batches",
    "test_runs",
    "approvals",
    "planned_tests",
    "test_plans",
    "analysis_snapshots",
    "target_authorizations",
    "project_sources",
    "artifacts",
    "project_memberships",
    "projects",
    "team_memberships",
    "teams",
    "state_transitions",
)


def upgrade() -> None:
    # ---- helper functions ------------------------------------------------
    op.execute(
        """
        CREATE FUNCTION public.forbid_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = '23514';
        END $$
        """
    )
    op.execute(
        """
        CREATE TABLE public.state_transitions (
            entity      text NOT NULL CHECK (entity IN ('test_run', 'test_batch')),
            from_status text NOT NULL,
            to_status   text NOT NULL,
            PRIMARY KEY (entity, from_status, to_status)
        )
        """
    )
    op.execute(f"INSERT INTO public.state_transitions VALUES {_transition_rows()}")
    op.execute(
        """
        CREATE FUNCTION public.enforce_status_transition() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.status IS DISTINCT FROM OLD.status AND NOT EXISTS (
                SELECT 1 FROM public.state_transitions
                WHERE entity = TG_ARGV[0]
                  AND from_status = OLD.status AND to_status = NEW.status
            ) THEN
                RAISE EXCEPTION 'invalid % transition: % -> %',
                    TG_ARGV[0], OLD.status, NEW.status USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )

    # ---- teams and access ------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE public.teams (
            id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name        text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
            created_by  uuid NOT NULL REFERENCES {USERS},
            created_at  timestamptz NOT NULL DEFAULT now(),
            updated_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX teams_name_lower_key ON public.teams (lower(name))")
    op.execute(
        f"""
        CREATE TABLE public.team_memberships (
            team_id    uuid NOT NULL REFERENCES public.teams (id) ON DELETE CASCADE,
            user_id    uuid NOT NULL REFERENCES {USERS} ON DELETE CASCADE,
            team_role  text NOT NULL DEFAULT 'member'
                       {_in("team_role", ("member", "owner"))},
            added_by   uuid REFERENCES {USERS},
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (team_id, user_id)
        )
        """
    )
    op.execute("CREATE INDEX team_memberships_user_idx ON public.team_memberships (user_id)")

    # ---- projects --------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE public.projects (
            id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name             text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
            description      text,
            owner_user_id    uuid NOT NULL REFERENCES {USERS},
            team_id          uuid REFERENCES public.teams (id),
            team_access      text NOT NULL DEFAULT 'none'
                             {_in("team_access", ("none", "read", "run"))},
            application_type text NOT NULL
                             {_in("application_type", ("web_app", "rest_api", "ai_app"))},
            status           text NOT NULL DEFAULT 'active'
                             {_in("status", ("active", "archived"))},
            archived_at      timestamptz,
            created_at       timestamptz NOT NULL DEFAULT now(),
            updated_at       timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT projects_archive_consistent
                CHECK ((status = 'archived') = (archived_at IS NOT NULL)),
            CONSTRAINT projects_team_access_needs_team
                CHECK (team_id IS NOT NULL OR team_access = 'none')
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX projects_owner_name_key "
        "ON public.projects (owner_user_id, lower(name))"
    )
    op.execute("CREATE INDEX projects_team_idx ON public.projects (team_id)")
    op.execute(
        f"""
        CREATE TABLE public.project_memberships (
            project_id   uuid NOT NULL REFERENCES public.projects (id) ON DELETE CASCADE,
            user_id      uuid NOT NULL REFERENCES {USERS} ON DELETE CASCADE,
            access_level text NOT NULL {_in("access_level", ("read", "run", "manage"))},
            granted_by   uuid REFERENCES {USERS},
            created_at   timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (project_id, user_id)
        )
        """
    )
    op.execute("CREATE INDEX project_memberships_user_idx ON public.project_memberships (user_id)")

    # ---- artifacts (metadata only; bytes live in the artifact store) -----
    # run_id / result_id foreign keys are added after those tables exist.
    op.execute(
        f"""
        CREATE TABLE public.artifacts (
            id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id        uuid NOT NULL REFERENCES public.projects (id),
            run_id            uuid,
            result_id         uuid,
            kind              text NOT NULL {
            _in(
                "kind",
                (
                    "upload",
                    "script",
                    "log",
                    "report",
                    "screenshot",
                    "coverage",
                    "trace",
                    "scan_output",
                    "other",
                ),
            )
        },
            storage_backend   text NOT NULL DEFAULT 'local'
                              {_in("storage_backend", ("local", "s3", "gcs"))},
            storage_key       text NOT NULL
                              CHECK (storage_key !~ '(^/|\\.\\.|\\\\)'),
            sha256            char(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{{64}}$'),
            size_bytes        bigint NOT NULL CHECK (size_bytes >= 0),
            content_type      text NOT NULL,
            original_filename text CHECK (length(original_filename) <= 255),
            validation_status text NOT NULL DEFAULT 'not_required'
                              {
            _in("validation_status", ("not_required", "pending", "accepted", "rejected"))
        },
            redaction_status  text NOT NULL DEFAULT 'not_required'
                              {_in("redaction_status", ("not_required", "pending", "redacted"))},
            retention_until   timestamptz,
            created_by        uuid REFERENCES {USERS},
            created_at        timestamptz NOT NULL DEFAULT now(),
            deleted_at        timestamptz,
            CONSTRAINT artifacts_storage_key UNIQUE (storage_backend, storage_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX artifacts_project_idx ON public.artifacts (project_id, created_at DESC)"
    )
    op.execute("CREATE INDEX artifacts_run_idx ON public.artifacts (run_id)")
    op.execute(
        "CREATE INDEX artifacts_retention_idx ON public.artifacts (retention_until) "
        "WHERE deleted_at IS NULL AND retention_until IS NOT NULL"
    )

    # ---- project sources and target authorization ------------------------
    url_re = "'^https?://[^/@]+(/|$|\\?)'"
    local_re = "'^https?://(localhost|127\\.0\\.0\\.1|\\[::1\\])(:[0-9]+)?(/|$|\\?)'"
    op.execute(
        f"""
        CREATE TABLE public.project_sources (
            id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id         uuid NOT NULL REFERENCES public.projects (id) ON DELETE CASCADE,
            source_type        text NOT NULL {
            _in("source_type", ("git_repository", "zip_upload", "localhost_url", "remote_url"))
        },
            name               text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
            git_url            text,
            git_ref            text,
            upload_artifact_id uuid REFERENCES public.artifacts (id),
            target_url         text,
            environment        text {
            _in("environment", ("local", "development", "staging", "production"))
        },
            is_active          boolean NOT NULL DEFAULT true,
            created_by         uuid NOT NULL REFERENCES {USERS},
            created_at         timestamptz NOT NULL DEFAULT now(),
            updated_at         timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT project_sources_shape CHECK (
                (source_type = 'git_repository'
                    AND git_url IS NOT NULL AND target_url IS NULL
                    AND upload_artifact_id IS NULL AND environment IS NULL)
                OR (source_type = 'zip_upload'
                    AND upload_artifact_id IS NOT NULL AND git_url IS NULL
                    AND git_ref IS NULL AND target_url IS NULL AND environment IS NULL)
                OR (source_type = 'localhost_url'
                    AND target_url ~* {local_re} AND environment = 'local'
                    AND git_url IS NULL AND git_ref IS NULL AND upload_artifact_id IS NULL)
                OR (source_type = 'remote_url'
                    AND target_url ~* {url_re}
                    AND environment IN ('development', 'staging', 'production')
                    AND git_url IS NULL AND git_ref IS NULL AND upload_artifact_id IS NULL)
            ),
            CONSTRAINT project_sources_no_embedded_credentials CHECK (
                (git_url IS NULL OR git_url !~ '://[^/]*@')
                AND (target_url IS NULL OR target_url !~ '://[^/]*@')
            )
        )
        """
    )
    op.execute("CREATE INDEX project_sources_project_idx ON public.project_sources (project_id)")

    op.execute(
        f"""
        CREATE TABLE public.target_authorizations (
            id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id     uuid NOT NULL REFERENCES public.projects (id) ON DELETE CASCADE,
            source_id      uuid NOT NULL REFERENCES public.project_sources (id) ON DELETE CASCADE,
            environment    text NOT NULL {
            _in("environment", ("development", "staging", "production"))
        },
            scope          jsonb NOT NULL,
            allowed_risk   text[] NOT NULL DEFAULT ARRAY['low'],
            status         text NOT NULL DEFAULT 'pending' {
            _in("status", ("pending", "approved", "rejected", "revoked", "expired"))
        },
            requested_by   uuid NOT NULL REFERENCES {USERS},
            decided_by     uuid REFERENCES {USERS},
            decided_at     timestamptz,
            decision_note  text,
            valid_from     timestamptz,
            valid_until    timestamptz,
            created_at     timestamptz NOT NULL DEFAULT now(),
            updated_at     timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ta_scope_is_object CHECK (jsonb_typeof(scope) = 'object'),
            CONSTRAINT ta_allowed_risk_values
                CHECK (allowed_risk <@ ARRAY['low', 'medium', 'high', 'critical']),
            CONSTRAINT ta_decision_recorded CHECK (
                status = 'pending'
                OR (decided_by IS NOT NULL AND decided_at IS NOT NULL)
                OR status = 'expired'
            ),
            CONSTRAINT ta_approved_needs_window CHECK (
                status <> 'approved' OR (valid_from IS NOT NULL AND valid_until IS NOT NULL
                                         AND valid_until > valid_from)
            ),
            -- Production testing is blocked by default; when ever authorized it must
            -- be time-boxed, carry a written justification, and be decided by a
            -- different person than the requester.
            CONSTRAINT ta_production_guard CHECK (
                environment <> 'production' OR (
                    (decided_by IS NULL OR decided_by <> requested_by)
                    AND (status <> 'approved' OR length(coalesce(decision_note, '')) >= 10)
                )
            )
        )
        """
    )
    op.execute("CREATE INDEX ta_project_idx ON public.target_authorizations (project_id)")
    op.execute(
        "CREATE INDEX ta_source_status_idx ON public.target_authorizations (source_id, status)"
    )

    op.execute(
        f"""
        CREATE TABLE public.analysis_snapshots (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id      uuid NOT NULL REFERENCES public.projects (id) ON DELETE CASCADE,
            source_id       uuid NOT NULL REFERENCES public.project_sources (id),
            commit_sha      text CHECK (commit_sha ~ '^[0-9a-f]{{7,64}}$'),
            content_sha256  char(64) CHECK (content_sha256 ~ '^[0-9a-f]{{64}}$'),
            detected        jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            status          text NOT NULL DEFAULT 'pending'
                            {_in("status", ("pending", "completed", "failed"))},
            error_summary   text,
            created_by      uuid REFERENCES {USERS},
            created_at      timestamptz NOT NULL DEFAULT now(),
            completed_at    timestamptz
        )
        """
    )
    op.execute(
        "CREATE INDEX analysis_snapshots_project_idx ON public.analysis_snapshots (project_id, created_at DESC)"
    )

    # ---- test plans ------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE public.test_plans (
            id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id  uuid NOT NULL REFERENCES public.projects (id) ON DELETE CASCADE,
            snapshot_id uuid REFERENCES public.analysis_snapshots (id),
            version     integer NOT NULL CHECK (version >= 1),
            plan_mode   text NOT NULL {
            _in("plan_mode", ("automatic", "prompt_based", "developer_defined"))
        },
            prompt      text,
            status      text NOT NULL DEFAULT 'draft' {
            _in("status", ("draft", "pending_approval", "approved", "rejected", "superseded"))
        },
            risk_level  text NOT NULL DEFAULT 'low' {_in("risk_level", RISK)},
            summary     text,
            created_by  uuid NOT NULL REFERENCES {USERS},
            created_at  timestamptz NOT NULL DEFAULT now(),
            updated_at  timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT test_plans_project_version UNIQUE (project_id, version),
            CONSTRAINT test_plans_prompt_mode CHECK (
                (plan_mode = 'prompt_based') = (prompt IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE public.planned_tests (
            id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            plan_id        uuid NOT NULL REFERENCES public.test_plans (id) ON DELETE CASCADE,
            ordinal        integer NOT NULL CHECK (ordinal >= 1),
            name           text NOT NULL CHECK (length(name) BETWEEN 1 AND 300),
            category       text NOT NULL {
            _in(
                "category",
                (
                    "functional",
                    "api",
                    "ui",
                    "security",
                    "accessibility",
                    "performance",
                    "llm_security",
                    "agent_security",
                    "regression",
                    "custom",
                ),
            )
        },
            tool           text NOT NULL,
            origin         text NOT NULL {
            _in("origin", ("recommended", "prompt", "developer_defined"))
        },
            definition     jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            script_artifact_id uuid REFERENCES public.artifacts (id),
            risk_level     text NOT NULL {_in("risk_level", RISK)},
            requires_approval boolean NOT NULL DEFAULT false,
            rationale      text,
            status         text NOT NULL DEFAULT 'planned' {_in("status", PLANNED_TEST_STATUSES)},
            created_at     timestamptz NOT NULL DEFAULT now(),
            updated_at     timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT planned_tests_plan_ordinal UNIQUE (plan_id, ordinal),
            CONSTRAINT planned_tests_definition_is_object CHECK (jsonb_typeof(definition) = 'object'),
            -- High/critical risk always needs approval; the database enforces the floor.
            CONSTRAINT planned_tests_high_risk_needs_approval
                CHECK (risk_level IN ('low', 'medium') OR requires_approval),
            CONSTRAINT planned_tests_custom_script_has_artifact
                CHECK (category <> 'custom' OR script_artifact_id IS NOT NULL
                       OR definition ? 'command_ref')
        )
        """
    )
    op.execute("CREATE INDEX planned_tests_plan_idx ON public.planned_tests (plan_id)")

    op.execute(
        f"""
        CREATE TABLE public.approvals (
            id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            plan_id          uuid REFERENCES public.test_plans (id) ON DELETE CASCADE,
            planned_test_id  uuid REFERENCES public.planned_tests (id) ON DELETE CASCADE,
            authorization_id uuid REFERENCES public.target_authorizations (id) ON DELETE CASCADE,
            risk_level       text NOT NULL {_in("risk_level", RISK)},
            decision         text NOT NULL DEFAULT 'pending'
                             {_in("decision", ("pending", "approved", "rejected"))},
            requested_by     uuid NOT NULL REFERENCES {USERS},
            decided_by       uuid REFERENCES {USERS},
            reason           text,
            created_at       timestamptz NOT NULL DEFAULT now(),
            decided_at       timestamptz,
            CONSTRAINT approvals_one_subject
                CHECK (num_nonnulls(plan_id, planned_test_id, authorization_id) = 1),
            CONSTRAINT approvals_decision_recorded CHECK (
                (decision = 'pending') = (decided_by IS NULL AND decided_at IS NULL)
            ),
            CONSTRAINT approvals_reject_needs_reason
                CHECK (decision <> 'rejected' OR length(coalesce(reason, '')) > 0)
        )
        """
    )
    op.execute(
        "CREATE INDEX approvals_pending_idx ON public.approvals (created_at) WHERE decision = 'pending'"
    )
    op.execute("CREATE INDEX approvals_plan_idx ON public.approvals (plan_id)")

    # ---- runs, batches, results, job events ------------------------------
    op.execute(
        f"""
        CREATE TABLE public.test_runs (
            id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id         uuid NOT NULL REFERENCES public.projects (id),
            plan_id            uuid NOT NULL REFERENCES public.test_plans (id),
            parent_run_id      uuid REFERENCES public.test_runs (id),
            kind               text NOT NULL DEFAULT 'execution'
                               {_in("kind", ("execution", "regression_verification"))},
            status             text NOT NULL DEFAULT 'queued' {_in("status", RUN_STATUSES)},
            idempotency_key    text CHECK (length(idempotency_key) BETWEEN 8 AND 128),
            requested_by       uuid NOT NULL REFERENCES {USERS},
            timeout_seconds    integer NOT NULL DEFAULT 3600 CHECK (timeout_seconds BETWEEN 1 AND 86400),
            cancel_requested_at timestamptz,
            cancel_requested_by uuid REFERENCES {USERS},
            started_at         timestamptz,
            finished_at        timestamptz,
            error_code         text,
            error_summary      text,
            created_at         timestamptz NOT NULL DEFAULT now(),
            updated_at         timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT test_runs_finished_after_started
                CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at),
            CONSTRAINT test_runs_cancel_consistent
                CHECK ((cancel_requested_at IS NULL) = (cancel_requested_by IS NULL)),
            CONSTRAINT test_runs_terminal_has_finish CHECK (
                status NOT IN ('completed', 'failed', 'cancelled', 'timed_out')
                OR finished_at IS NOT NULL
            )
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX test_runs_idempotency_key ON public.test_runs "
        "(project_id, idempotency_key) WHERE idempotency_key IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX test_runs_project_created_idx ON public.test_runs (project_id, created_at DESC)"
    )
    op.execute("CREATE INDEX test_runs_plan_idx ON public.test_runs (plan_id)")
    op.execute(
        "CREATE INDEX test_runs_active_idx ON public.test_runs (status) "
        "WHERE status IN ('queued', 'dispatched', 'running', 'cancel_requested')"
    )
    op.execute(
        "CREATE TRIGGER test_runs_status_guard BEFORE UPDATE OF status ON public.test_runs "
        "FOR EACH ROW EXECUTE FUNCTION public.enforce_status_transition('test_run')"
    )

    op.execute(
        f"""
        CREATE TABLE public.test_batches (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id          uuid NOT NULL REFERENCES public.test_runs (id) ON DELETE CASCADE,
            ordinal         integer NOT NULL CHECK (ordinal >= 1),
            status          text NOT NULL DEFAULT 'queued' {_in("status", RUN_STATUSES)},
            attempt         integer NOT NULL DEFAULT 1 CHECK (attempt >= 1),
            max_attempts    integer NOT NULL DEFAULT 1 CHECK (max_attempts >= 1),
            timeout_seconds integer NOT NULL DEFAULT 1800 CHECK (timeout_seconds BETWEEN 1 AND 86400),
            queue_task_id   text,
            worker_id       text,
            started_at      timestamptz,
            finished_at     timestamptz,
            error_code      text,
            error_summary   text,
            created_at      timestamptz NOT NULL DEFAULT now(),
            updated_at      timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT test_batches_run_ordinal UNIQUE (run_id, ordinal),
            CONSTRAINT test_batches_attempt_bound CHECK (attempt <= max_attempts),
            CONSTRAINT test_batches_terminal_has_finish CHECK (
                status NOT IN ('completed', 'failed', 'cancelled', 'timed_out')
                OR finished_at IS NOT NULL
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX test_batches_active_idx ON public.test_batches (status) "
        "WHERE status IN ('queued', 'dispatched', 'running', 'cancel_requested')"
    )
    op.execute(
        "CREATE TRIGGER test_batches_status_guard BEFORE UPDATE OF status ON public.test_batches "
        "FOR EACH ROW EXECUTE FUNCTION public.enforce_status_transition('test_batch')"
    )

    op.execute(
        f"""
        CREATE TABLE public.test_results (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id          uuid NOT NULL REFERENCES public.test_runs (id) ON DELETE CASCADE,
            batch_id        uuid NOT NULL REFERENCES public.test_batches (id) ON DELETE CASCADE,
            planned_test_id uuid NOT NULL REFERENCES public.planned_tests (id),
            attempt         integer NOT NULL DEFAULT 1 CHECK (attempt >= 1),
            status          text NOT NULL {_in("status", RESULT_STATUSES)},
            summary         text,
            exit_code       integer,
            duration_ms     bigint CHECK (duration_ms >= 0),
            started_at      timestamptz,
            finished_at     timestamptz,
            created_at      timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT test_results_attempt_unique UNIQUE (batch_id, planned_test_id, attempt)
        )
        """
    )
    op.execute("CREATE INDEX test_results_run_idx ON public.test_results (run_id)")
    op.execute(
        "CREATE INDEX test_results_planned_test_idx ON public.test_results (planned_test_id)"
    )

    op.execute(
        "ALTER TABLE public.artifacts "
        "ADD CONSTRAINT artifacts_run_fk FOREIGN KEY (run_id) REFERENCES public.test_runs (id), "
        "ADD CONSTRAINT artifacts_result_fk FOREIGN KEY (result_id) REFERENCES public.test_results (id)"
    )

    op.execute(
        f"""
        CREATE TABLE public.job_events (
            id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            run_id        uuid NOT NULL REFERENCES public.test_runs (id) ON DELETE CASCADE,
            batch_id      uuid REFERENCES public.test_batches (id) ON DELETE CASCADE,
            event_type    text NOT NULL {
            _in(
                "event_type",
                (
                    "transition",
                    "retry_scheduled",
                    "cancel_requested",
                    "timeout",
                    "worker_lost",
                    "recovered",
                    "note",
                ),
            )
        },
            from_status   text,
            to_status     text,
            actor_user_id uuid REFERENCES {USERS},
            worker_id     text,
            detail        jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            created_at    timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX job_events_run_idx ON public.job_events (run_id, id)")
    op.execute(
        "CREATE TRIGGER job_events_append_only BEFORE UPDATE ON public.job_events "
        "FOR EACH ROW EXECUTE FUNCTION public.forbid_mutation()"
    )

    # ---- findings --------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE public.findings (
            id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id         uuid NOT NULL REFERENCES public.projects (id) ON DELETE CASCADE,
            first_run_id       uuid REFERENCES public.test_runs (id),
            last_run_id        uuid REFERENCES public.test_runs (id),
            result_id          uuid REFERENCES public.test_results (id),
            fingerprint        text NOT NULL CHECK (length(fingerprint) BETWEEN 8 AND 200),
            title              text NOT NULL CHECK (length(title) BETWEEN 1 AND 300),
            description        text,
            category           text NOT NULL,
            detected_by        text NOT NULL,
            severity           text NOT NULL {
            _in("severity", ("info", "low", "medium", "high", "critical"))
        },
            verification_state text NOT NULL DEFAULT 'unverified' {
            _in(
                "verification_state",
                ("unverified", "likely", "confirmed", "not_reproduced", "inconclusive"),
            )
        },
            status             text NOT NULL DEFAULT 'new' {
            _in(
                "status",
                (
                    "new",
                    "triaged",
                    "in_progress",
                    "fixed",
                    "verified_fixed",
                    "accepted_risk",
                    "false_positive",
                    "reopened",
                ),
            )
        },
            assigned_to        uuid REFERENCES {USERS},
            resolved_at        timestamptz,
            created_at         timestamptz NOT NULL DEFAULT now(),
            updated_at         timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT findings_project_fingerprint UNIQUE (project_id, fingerprint)
        )
        """
    )
    op.execute(
        "CREATE INDEX findings_project_status_idx ON public.findings (project_id, status, severity)"
    )
    op.execute("CREATE INDEX findings_last_run_idx ON public.findings (last_run_id)")

    op.execute(
        f"""
        CREATE TABLE public.finding_events (
            id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            finding_id    uuid NOT NULL REFERENCES public.findings (id) ON DELETE CASCADE,
            event_type    text NOT NULL {
            _in(
                "event_type",
                (
                    "created",
                    "status_changed",
                    "verification_changed",
                    "assigned",
                    "evidence_added",
                    "comment",
                    "seen_again",
                ),
            )
        },
            from_value    text,
            to_value      text,
            actor_user_id uuid REFERENCES {USERS},
            detail        jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            created_at    timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX finding_events_finding_idx ON public.finding_events (finding_id, id)")
    op.execute(
        "CREATE TRIGGER finding_events_append_only BEFORE UPDATE ON public.finding_events "
        "FOR EACH ROW EXECUTE FUNCTION public.forbid_mutation()"
    )

    op.execute(
        f"""
        CREATE TABLE public.finding_evidence (
            finding_id  uuid NOT NULL REFERENCES public.findings (id) ON DELETE CASCADE,
            artifact_id uuid NOT NULL REFERENCES public.artifacts (id),
            note        text,
            added_by    uuid REFERENCES {USERS},
            created_at  timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (finding_id, artifact_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX finding_evidence_artifact_idx ON public.finding_evidence (artifact_id)"
    )

    # Evidence-backed findings: a finding cannot be 'confirmed' without evidence, and
    # the last evidence row of a confirmed finding cannot be removed. Deferred so a
    # finding and its evidence can be written in one transaction.
    op.execute(
        """
        CREATE FUNCTION public.check_confirmed_has_evidence() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE fid uuid;
        BEGIN
            IF TG_TABLE_NAME = 'findings' THEN fid := NEW.id; ELSE fid := OLD.finding_id; END IF;
            IF EXISTS (SELECT 1 FROM public.findings WHERE id = fid AND verification_state = 'confirmed')
               AND NOT EXISTS (SELECT 1 FROM public.finding_evidence WHERE finding_id = fid) THEN
                RAISE EXCEPTION 'finding % is confirmed but has no evidence', fid
                    USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END $$
        """
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER findings_confirmed_needs_evidence "
        "AFTER INSERT OR UPDATE OF verification_state ON public.findings "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        "EXECUTE FUNCTION public.check_confirmed_has_evidence()"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER evidence_delete_keeps_confirmed "
        "AFTER DELETE ON public.finding_evidence "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        "EXECUTE FUNCTION public.check_confirmed_has_evidence()"
    )

    op.execute(
        f"""
        CREATE TABLE public.verification_attempts (
            id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            finding_id  uuid NOT NULL REFERENCES public.findings (id) ON DELETE CASCADE,
            run_id      uuid NOT NULL REFERENCES public.test_runs (id),
            outcome     text NOT NULL {_in("outcome", ("fixed", "not_fixed", "inconclusive"))},
            notes       text,
            created_by  uuid REFERENCES {USERS},
            created_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX verification_attempts_finding_idx ON public.verification_attempts (finding_id)"
    )
    op.execute(
        f"""
        CREATE TABLE public.regression_tests (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            finding_id      uuid NOT NULL REFERENCES public.findings (id) ON DELETE CASCADE,
            planned_test_id uuid REFERENCES public.planned_tests (id),
            status          text NOT NULL DEFAULT 'proposed'
                            {_in("status", ("proposed", "accepted", "rejected", "verified"))},
            proposed_by     uuid REFERENCES {USERS},
            decided_by      uuid REFERENCES {USERS},
            created_at      timestamptz NOT NULL DEFAULT now(),
            decided_at      timestamptz
        )
        """
    )
    op.execute("CREATE INDEX regression_tests_finding_idx ON public.regression_tests (finding_id)")

    # ---- LLM usage, policy, audit ---------------------------------------
    op.execute(
        f"""
        CREATE TABLE public.llm_usage (
            id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            project_id         uuid REFERENCES public.projects (id),
            run_id             uuid REFERENCES public.test_runs (id),
            requested_by       uuid REFERENCES {USERS},
            purpose            text NOT NULL {
            _in(
                "purpose",
                (
                    "analysis",
                    "planning",
                    "investigation",
                    "regression",
                    "verification",
                    "chat",
                    "other",
                ),
            )
        },
            provider           text NOT NULL DEFAULT 'gemini',
            model              text NOT NULL,
            input_tokens       integer NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
            output_tokens      integer NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
            estimated_cost_usd numeric(12, 6) NOT NULL DEFAULT 0 CHECK (estimated_cost_usd >= 0),
            blocked_by_budget  boolean NOT NULL DEFAULT false,
            created_at         timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX llm_usage_project_idx ON public.llm_usage (project_id, created_at DESC)"
    )
    op.execute("CREATE INDEX llm_usage_run_idx ON public.llm_usage (run_id)")

    op.execute(
        f"""
        CREATE TABLE public.policies (
            id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope      text NOT NULL {_in("scope", ("global", "project"))},
            project_id uuid REFERENCES public.projects (id) ON DELETE CASCADE,
            key        text NOT NULL CHECK (length(key) BETWEEN 1 AND 100),
            value      jsonb NOT NULL,
            updated_by uuid REFERENCES {USERS},
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT policies_scope_consistent
                CHECK ((scope = 'global') = (project_id IS NULL))
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX policies_global_key ON public.policies (key) WHERE scope = 'global'"
    )
    op.execute(
        "CREATE UNIQUE INDEX policies_project_key ON public.policies (project_id, key) "
        "WHERE scope = 'project'"
    )
    # Safe defaults: production testing blocked, high/critical need approval, LLM limits set.
    op.execute(
        """
        INSERT INTO public.policies (scope, key, value) VALUES
          ('global', 'production_testing', '{"allowed": false}'),
          ('global', 'approval_required_risk_levels', '["high", "critical"]'),
          ('global', 'llm_limits',
              '{"max_tokens_per_run": 200000, "max_cost_usd_per_run": 2.0,
                "max_cost_usd_per_day": 20.0, "deterministic_first": true}')
        """
    )

    op.execute(
        f"""
        CREATE TABLE public.audit_events (
            id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            occurred_at   timestamptz NOT NULL DEFAULT now(),
            actor_type    text NOT NULL {_in("actor_type", ("user", "system", "worker"))},
            actor_user_id uuid REFERENCES {USERS},
            action        text NOT NULL CHECK (length(action) BETWEEN 1 AND 100),
            target_type   text,
            target_id     text,
            project_id    uuid REFERENCES public.projects (id),
            outcome       text NOT NULL {_in("outcome", ("success", "denied", "failure"))},
            request_id    text,
            ip_address    inet,
            detail        jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            CONSTRAINT audit_user_actor CHECK ((actor_type = 'user') = (actor_user_id IS NOT NULL)
                                               OR actor_type <> 'user')
        )
        """
    )
    op.execute("CREATE INDEX audit_events_time_idx ON public.audit_events (occurred_at DESC)")
    op.execute(
        "CREATE INDEX audit_events_project_idx ON public.audit_events (project_id, occurred_at DESC)"
    )
    op.execute(
        "CREATE INDEX audit_events_actor_idx ON public.audit_events (actor_user_id, occurred_at DESC)"
    )
    op.execute(
        "CREATE INDEX audit_events_action_idx ON public.audit_events (action, occurred_at DESC)"
    )
    op.execute(
        "CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON public.audit_events "
        "FOR EACH ROW EXECUTE FUNCTION public.forbid_mutation()"
    )

    for table in UPDATED_AT_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_set_updated_at BEFORE UPDATE ON public.{table} "
            "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
        )


def downgrade() -> None:
    # Drops only objects created by this revision, in reverse dependency order, with
    # no CASCADE: unrelated objects in public are never touched.
    op.execute("ALTER TABLE public.artifacts DROP CONSTRAINT artifacts_run_fk")
    op.execute("ALTER TABLE public.artifacts DROP CONSTRAINT artifacts_result_fk")
    for table in CREATED_TABLES:
        op.execute(f"DROP TABLE public.{table}")
    op.execute("DROP FUNCTION public.check_confirmed_has_evidence()")
    op.execute("DROP FUNCTION public.enforce_status_transition()")
    op.execute("DROP FUNCTION public.forbid_mutation()")
