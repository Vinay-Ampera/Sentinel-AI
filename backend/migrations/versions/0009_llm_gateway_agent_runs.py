"""Stage 11: LLM gateway accounting and agent workflow records.

Revision ID: 0009_llm_gateway_agent_runs
Revises: 0008_finding_groups

``llm_usage`` (0002) already records tokens, estimated cost and ``blocked_by_budget``. This adds
what the gateway needs to account for every call honestly: the outcome (including the
``reserved`` state a call holds while it is in flight, so concurrent calls see each other's
budget use), the latency and attempt count, a hash of the redacted prompt (never the prompt
text), the prompt template version and the owning ``agent_run``. Existing rows stay valid
(``outcome`` defaults to ``ok``).

``agent_runs`` records one workflow invocation (project-scoped); ``agent_steps`` is its
append-only trace (one row per graph node transition, linked to the usage row of an LLM step).
Neither table holds a prompt, a secret or an access decision.

Regression-test proposals reuse the existing ``regression_tests`` table. It gains the project
scope, an optional ``result_id`` (a proposal may be drafted from a failed result instead of a
finding, so ``finding_id`` becomes nullable but exactly the subject it was drafted from is
recorded; deleting that result deletes its proposals), the agent run that
drafted it and the draft itself (title, rationale, target path, framework, code, expected
behaviour, cited evidence ids, risk flags and name overlaps found by deterministic checks). A
draft is text for a person to accept or reject: a trigger freezes its content once stored
and allows only ``proposed -> accepted | rejected`` and ``accepted -> verified``.
"""

from alembic import op

revision = "0009_llm_gateway_agent_runs"
down_revision = "0008_finding_groups"
branch_labels = None
depends_on = None

USERS = "app_user.users (id)"
WORKFLOWS = "('analysis', 'planning', 'investigation', 'regression', 'verification')"
OUTCOMES = (
    "('reserved', 'ok', 'invalid_output', 'timeout', 'rate_limited', 'unavailable', "
    "'provider_error', 'blocked_by_budget', 'deadline_exceeded')"
)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE public.agent_runs (
            id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id       uuid NOT NULL REFERENCES public.projects (id) ON DELETE CASCADE,
            workflow         text NOT NULL CONSTRAINT agent_runs_workflow_check
                             CHECK (workflow IN {WORKFLOWS}),
            subject_type     text CHECK (subject_type IS NULL OR length(subject_type) <= 40),
            subject_id       uuid,
            status           text NOT NULL DEFAULT 'running' CONSTRAINT agent_runs_status_check
                             CHECK (status IN ('running', 'succeeded', 'degraded', 'failed')),
            degraded_reason  text CHECK (degraded_reason IS NULL OR length(degraded_reason) <= 60),
            requested_by     uuid REFERENCES {USERS},
            input_hash       text CHECK (input_hash IS NULL OR length(input_hash) = 64),
            template_version text CHECK (template_version IS NULL OR length(template_version) <= 40),
            model            text CHECK (model IS NULL OR length(model) <= 200),
            used_llm         boolean NOT NULL DEFAULT false,
            cache_hit        boolean NOT NULL DEFAULT false,
            result           jsonb,
            started_at       timestamptz NOT NULL DEFAULT now(),
            finished_at      timestamptz,
            created_at       timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT agent_runs_terminal_has_finish
                CHECK ((status = 'running') = (finished_at IS NULL)),
            CONSTRAINT agent_runs_degraded_has_reason
                CHECK (status <> 'degraded' OR degraded_reason IS NOT NULL)
        )
        """
    )
    op.execute(
        "CREATE INDEX agent_runs_project_idx ON public.agent_runs (project_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX agent_runs_running_idx ON public.agent_runs (started_at) "
        "WHERE status = 'running'"
    )
    op.execute(
        "CREATE INDEX agent_runs_cache_idx ON public.agent_runs "
        "(project_id, workflow, input_hash) WHERE status IN ('succeeded', 'degraded')"
    )

    op.execute(
        f"""
        ALTER TABLE public.llm_usage
            ADD COLUMN agent_run_id     uuid REFERENCES public.agent_runs (id) ON DELETE SET NULL,
            ADD COLUMN outcome          text NOT NULL DEFAULT 'ok'
                                        CONSTRAINT llm_usage_outcome_check CHECK (outcome IN {OUTCOMES}),
            ADD COLUMN latency_ms       integer CHECK (latency_ms IS NULL OR latency_ms >= 0),
            ADD COLUMN attempts         smallint NOT NULL DEFAULT 1 CHECK (attempts BETWEEN 0 AND 20),
            ADD COLUMN prompt_hash      text CHECK (prompt_hash IS NULL OR length(prompt_hash) = 64),
            ADD COLUMN template_version text CHECK (template_version IS NULL OR length(template_version) <= 40)
        """
    )
    op.execute("CREATE INDEX llm_usage_agent_run_idx ON public.llm_usage (agent_run_id)")
    op.execute(
        "CREATE INDEX llm_usage_day_idx ON public.llm_usage (created_at DESC) "
        "WHERE NOT blocked_by_budget"
    )

    op.execute(
        """
        CREATE TABLE public.agent_steps (
            id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            agent_run_id  uuid NOT NULL REFERENCES public.agent_runs (id) ON DELETE CASCADE,
            seq           integer NOT NULL CHECK (seq >= 1),
            node          text NOT NULL CHECK (length(node) BETWEEN 1 AND 80),
            kind          text NOT NULL CONSTRAINT agent_steps_kind_check
                          CHECK (kind IN ('deterministic', 'decision', 'llm', 'policy')),
            outcome       text NOT NULL CHECK (length(outcome) BETWEEN 1 AND 60),
            detail        jsonb NOT NULL DEFAULT '{}'::jsonb,
            llm_usage_id  bigint REFERENCES public.llm_usage (id) ON DELETE SET NULL,
            created_at    timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT agent_steps_run_seq UNIQUE (agent_run_id, seq)
        )
        """
    )
    op.execute(
        "CREATE TRIGGER agent_steps_append_only BEFORE UPDATE ON public.agent_steps "
        "FOR EACH ROW EXECUTE FUNCTION public.forbid_mutation()"
    )


    op.execute(
        """
        ALTER TABLE public.regression_tests
            ADD COLUMN project_id        uuid REFERENCES public.projects (id) ON DELETE CASCADE,
            ADD COLUMN result_id         uuid REFERENCES public.test_results (id) ON DELETE CASCADE,
            ADD COLUMN agent_run_id      uuid REFERENCES public.agent_runs (id) ON DELETE SET NULL,
            ADD COLUMN title             text,
            ADD COLUMN rationale         text,
            ADD COLUMN target_path       text,
            ADD COLUMN framework         text,
            ADD COLUMN code              text,
            ADD COLUMN expected_behavior text,
            ADD COLUMN evidence_ids      jsonb NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN risk_flags        jsonb NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN overlap           jsonb NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN decision_note     text
        """
    )
    op.execute(
        "UPDATE public.regression_tests rt SET project_id = f.project_id, "
        "title = '(earlier proposal)', rationale = '', target_path = 'unknown', "
        "framework = 'pytest', code = '', expected_behavior = '' "
        "FROM public.findings f WHERE f.id = rt.finding_id"
    )
    op.execute(
        """
        ALTER TABLE public.regression_tests
            ALTER COLUMN finding_id DROP NOT NULL,
            ALTER COLUMN project_id SET NOT NULL,
            ALTER COLUMN title SET NOT NULL,
            ALTER COLUMN rationale SET NOT NULL,
            ALTER COLUMN target_path SET NOT NULL,
            ALTER COLUMN framework SET NOT NULL,
            ALTER COLUMN code SET NOT NULL,
            ALTER COLUMN expected_behavior SET NOT NULL,
            ADD CONSTRAINT regression_tests_subject
                CHECK (finding_id IS NOT NULL OR result_id IS NOT NULL),
            ADD CONSTRAINT regression_tests_framework_check
                CHECK (framework IN ('pytest', 'jest', 'vitest')),
            ADD CONSTRAINT regression_tests_sizes
                CHECK (length(title) <= 120 AND length(rationale) <= 500
                       AND length(target_path) <= 200 AND length(code) <= 20000
                       AND length(expected_behavior) <= 400
                       AND length(coalesce(decision_note, '')) <= 1000)
        """
    )
    op.execute(
        "CREATE INDEX regression_tests_project_idx ON public.regression_tests "
        "(project_id, created_at DESC)"
    )
    op.execute(
        """
        CREATE FUNCTION public.regression_tests_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.project_id IS DISTINCT FROM OLD.project_id
               OR NEW.finding_id IS DISTINCT FROM OLD.finding_id
               OR NEW.result_id IS DISTINCT FROM OLD.result_id
               OR NEW.title IS DISTINCT FROM OLD.title
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
    )
    op.execute(
        "CREATE TRIGGER regression_tests_guard BEFORE UPDATE ON public.regression_tests "
        "FOR EACH ROW EXECUTE FUNCTION public.regression_tests_guard()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS regression_tests_guard ON public.regression_tests")
    op.execute("DROP FUNCTION IF EXISTS public.regression_tests_guard()")
    op.execute("DROP INDEX IF EXISTS public.regression_tests_project_idx")
    # Drafts that came from a failed result have no finding; the original shape cannot hold them.
    op.execute("DELETE FROM public.regression_tests WHERE finding_id IS NULL")
    op.execute(
        "ALTER TABLE public.regression_tests DROP CONSTRAINT regression_tests_sizes, "
        "DROP CONSTRAINT regression_tests_framework_check, DROP CONSTRAINT regression_tests_subject"
    )
    op.execute(
        "ALTER TABLE public.regression_tests ALTER COLUMN finding_id SET NOT NULL, "
        "DROP COLUMN decision_note, DROP COLUMN overlap, DROP COLUMN risk_flags, "
        "DROP COLUMN evidence_ids, DROP COLUMN expected_behavior, DROP COLUMN code, "
        "DROP COLUMN framework, DROP COLUMN target_path, DROP COLUMN rationale, "
        "DROP COLUMN title, DROP COLUMN agent_run_id, DROP COLUMN result_id, "
        "DROP COLUMN project_id"
    )
    op.execute("DROP TABLE public.agent_steps")
    op.execute("DROP INDEX IF EXISTS public.llm_usage_day_idx")
    op.execute("DROP INDEX IF EXISTS public.llm_usage_agent_run_idx")
    op.execute(
        "ALTER TABLE public.llm_usage DROP COLUMN template_version, DROP COLUMN prompt_hash, "
        "DROP COLUMN attempts, DROP COLUMN latency_ms, DROP COLUMN outcome, "
        "DROP COLUMN agent_run_id"
    )
    op.execute("DROP TABLE public.agent_runs")
