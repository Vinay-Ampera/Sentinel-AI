# Database Schema

> Status: **Stage 2 design, implemented as Alembic migrations** `0001_app_user_schema` and `0002_public_application_schema` (`backend/migrations/versions/`). Verified on a disposable PostgreSQL 17 database (see `IMPLEMENTATION_PLAN.md` §21). **Not yet applied to the real `sentinel-ai` database** — see "Applying to the real database". The migrations are the source of truth for exact DDL; this file explains the design.

## Layout
- Database: `sentinel-ai` (existing). Alembic version table: `public.alembic_version`.
- Schema **`app_user`**: accounts, roles, sessions, password-reset tokens.
- Schema **`public`**: everything else (projects, plans, runs, findings, artifacts metadata, audit).
- Conventions: `uuid` primary keys (`gen_random_uuid()`), `timestamptz` timestamps, `text` + `CHECK` for status vocabularies (cheaper to evolve than PG enums), `updated_at` maintained by trigger `public.set_updated_at()`, FKs explicit (cross-schema FKs point at `app_user.users`). No secrets, no raw tokens, no artifact bytes in rows.

## `app_user` schema
| Table | Purpose | Key constraints |
|---|---|---|
| `roles` | `developer` (10), `admin` (20), `super_admin` (30); seeded reference data | name CHECK; unique rank |
| `users` | accounts | unique lowercase `email` (CHECK `email = lower(email)`); `password_hash` (Argon2id string, see ADR-0002); `role_name` FK; `is_active`; `failed_login_count`, `locked_until`; deactivation consistency |
| `sessions` | server-side sessions | `token_hash` (32-byte keyed hash, unique) — raw token never stored; `csrf_token_hash`; `idle_expires_at`, `absolute_expires_at`, `revoked_at`; partial index on active sessions per user |
| `password_reset_tokens` | one-time reset tokens (hashed) | `token_hash` unique; `expires_at > created_at`; `used_at` |

No user is seeded (no credentials in migrations). The first Super Admin is created by a documented CLI/management command in Stage 4.

## `public` schema
**Access:** `teams` (unique case-insensitive name), `team_memberships` (`member|owner`), `project_memberships` (`read|run|manage`).
**Projects:** `projects` (`owner_user_id` NOT NULL, optional `team_id`, `team_access none|read|run`, `application_type web_app|rest_api|ai_app`, archive consistency; unique `(owner, lower(name))`). `project_sources` (one row per input; type-specific shape enforced by a CHECK — see below). `target_authorizations` (explicit authorization for remote targets). `analysis_snapshots` (commit SHA / content digest + detected stack).
**Planning:** `test_plans` (per-project `version`, `plan_mode automatic|prompt_based|developer_defined`, prompt required iff prompt-based), `planned_tests` (`origin`, `risk_level`, `requires_approval`, status per blueprint: planned/approved/executed/skipped/blocked/failed_to_start/deferred), `approvals` (exactly one subject: plan, planned test, or target authorization).
**Execution:** `test_runs` (`parent_run_id` for reruns, `idempotency_key`, `timeout_seconds`, cancel columns), `test_batches` (`attempt <= max_attempts`, `queue_task_id`, `worker_id`), `test_results` (unique per batch/test/attempt), `job_events` (append-only transition log), `state_transitions` (reference table, see Job design).
**Findings (extended by migration `0007_findings`, Stage 10):** adds `confidence` (low|medium|high, default low), `rule_id`, `file_path`, `line_number`, `source_id` (the scanned `project_sources` row), `limitations`, `occurrences` to `findings`; `verification_attempts` gains `method` (`rescan`|`manual`) and `evidence_artifact_id`; `finding_events.event_type` gains `reopened` and `verification_attempt`. Scanners create rows `new` + `unverified`. Original description: `findings` (unique `(project_id, fingerprint)`; `severity`; `verification_state` unverified|likely|confirmed|not_reproduced|inconclusive; `status` new…reopened), `finding_events` (append-only), `finding_evidence` (finding ↔ artifact), `verification_attempts`, `regression_tests`.
**Artifacts:** `artifacts` (metadata + `storage_backend`/`storage_key`, `sha256`, `size_bytes`, `content_type`, validation/redaction status, `retention_until`, soft delete).
**Governance:** `policies` (global/project key→JSON; seeded safe defaults), `llm_usage` (tokens/cost per call, `blocked_by_budget`; 0009 adds `outcome`, `attempts`, `latency_ms`, `prompt_hash`, `template_version`, `agent_run_id`), `agent_runs` and append-only `agent_steps` (0009; workflow trace, no prompts), `regression_tests` (extended in 0009 to hold drafted tests: project scope, optional result subject, draft text, risk flags, frozen by trigger), `audit_events` (append-only).

**Deferred to later stages (no table yet, by design):** trace resolution, metrics and a raw log store (never planned for Stage 12: trace ids are stored only as opaque references), chat history (Stage 14), report records (Stage 14), accessibility/LLM-security result detail beyond `test_results` + artifacts (Stages 9–13). Adding them requires a new migration and a doc update; no feature may assume them now.

**Observability (migration `0010_observability_alerts`, Stage 12, ADR-0011; written and tested on a disposable database, not applied to the real one):** `ingest_keys` (project-scoped write-only credentials; only a 32-byte keyed hash is stored, `key_id` is a public 12-hex id, expiry and revocation); `event_groups` (one row per project and versioned fingerprint: service, environment, level class, error type, normalized message, first/last seen, total count, `has_stack`, `is_overflow`); `event_buckets` (hourly UTC counts per group); `events` (at most 20 redacted samples per group, ordered by an identity column; correlation claims, their verification and redaction counts; never a raw payload); `ingest_stats` (per project and day: accepted, dropped by reason, rule evaluation errors); `alerts` (one open alert per project, rule and subject by a partial unique index; severity, status `open|acknowledged|resolved`, measured and evidence JSON of facts and ids only, `cause_status`); `alert_history` (append-only). `regression_tests` gains `alert_id` and `event_group_id` (plain restrictive foreign keys, frozen with the draft; retention never deletes an alert or group a proposal points to). Every table carries `project_id`.

## Rules enforced by the database
| Rule | Mechanism |
|---|---|
| Source shape per type (git needs `git_url`; zip needs an upload artifact; `localhost_url` host must be localhost/127.0.0.1/[::1] and environment `local`; `remote_url` environment `development|staging|production`) | `project_sources_shape` CHECK |
| No credentials embedded in URLs | `project_sources_no_embedded_credentials` CHECK |
| Production testing: any approved production authorization must be time-boxed, carry a ≥10-char justification, and be decided by someone other than the requester | `ta_production_guard`, `ta_approved_needs_window` CHECKs |
| Production blocked by default | seeded policy `production_testing = {"allowed": false}` + application check (a production source needs an `approved`, unexpired authorization **and** the policy flag) |
| High/critical-risk planned tests always require approval | `planned_tests_high_risk_needs_approval` CHECK |
| Run/batch status transitions follow the documented machine | trigger `enforce_status_transition` against `state_transitions`; terminal states require `finished_at` |
| Batch retries bounded | `attempt <= max_attempts` |
| Evidence-backed findings: a `confirmed` finding must have ≥1 evidence row; the last evidence row of a confirmed finding cannot be deleted | deferred constraint triggers |
| Audit, job and finding event logs are append-only | `forbid_mutation` triggers (UPDATE/DELETE blocked on `audit_events`; UPDATE blocked on the other two — cascade deletes with the parent are allowed) |
| Artifact storage keys cannot be absolute or contain `..`/backslashes; `sha256` is 64 hex chars | CHECKs |
| Idempotent run creation | unique `(project_id, idempotency_key)` where not null |
| One open alert per (project, rule, subject); a resolved alert has `closed_at` | partial unique index `alerts_one_open`, `alerts_closed_consistent` CHECK |
| Ingest key shape and lifetime; trace/span id formats; event field sizes | CHECKs on `ingest_keys`, `events`, `event_groups` |
| Alert history is append-only | `forbid_mutation` trigger |

## Ownership and access scope (authoritative statement)
A user may access a project iff **any** of: (1) `projects.owner_user_id = user`; (2) a `project_memberships` row; (3) the user is in `projects.team_id` and `team_access` ≥ requested level; (4) the user is **Admin/Super Admin** acting on a project in their administrative scope (Admin: projects they own, teams they own, or explicitly delegated; Super Admin: all, every access audited). Access levels: `read` < `run` < `manage`. Child records (sources, plans, runs, batches, results, findings, artifacts, audit rows) are authorized **only through `project_id`** — a run/finding/artifact ID alone is never proof of access. Every repository-layer query for a child entity joins to `projects` and applies the access predicate. Cross-project access tests are mandatory (TEST_STRATEGY).

## Indexes
FK columns used for joins; `(project_id, created_at DESC)` on runs/artifacts/snapshots/llm_usage/audit; partial indexes for active runs/batches, pending approvals, active sessions, retention sweeps; unique indexes for identity, idempotency, fingerprints, policy keys.

## Retention assumptions (to confirm before production; Q19)
Artifacts carry `retention_until` (default proposal: logs/scan output 90 days, reports and finding evidence kept while the finding is open + 1 year, uploads/source archives 30 days after the last run, screenshots 90 days). `audit_events` are not deleted by application code. A retention sweeper (later stage) soft-deletes (`deleted_at`) then removes bytes; rows needed for audit/regression comparisons remain.

## Applying to the real database
Never ad hoc SQL. With `DATABASE_URL` exported from your untracked `backend/.env`:
```bash
cd backend
poetry run alembic current                  # expect no revision on a fresh database
poetry run alembic upgrade head --sql > /tmp/stage2.sql   # optional: review the DDL first
poetry run alembic upgrade head
```
Before upgrading, inspect existing objects (read-only):
`psql "$DATABASE_URL" -c '\dn' -c '\dt *.*'` (filter out `pg_catalog`/`information_schema`). Migration behavior on existing data: `CREATE SCHEMA IF NOT EXISTS app_user`; every table is a plain `CREATE TABLE`, so a name collision **aborts the whole migration atomically (transactional DDL) without touching existing data** — verified. `downgrade` drops only objects the migrations created (no CASCADE) and drops `app_user` only if empty. Downgrading destroys the data in the tables it drops; take a `pg_dump` first on any database holding real data.

## Migration notes
Models/ORM mappings are not part of Stage 2; Stage 3/4 add SQLAlchemy models and must be checked against this schema (the integration tests in `backend/tests/integration/test_migrations.py` pin the table sets and key constraints).

## Migration 0003 - plan integrity (Stage 6)
Additive only; applies on top of 0002 without touching existing rows. Apply with `alembic upgrade head` after reviewing `alembic upgrade 0002_public_application_schema:0003_plan_integrity --sql`.
- `test_plans`: `content_sha256` (hash of the reviewed content), `policy_snapshot`, `submitted_by`, `submitted_at`; a plan that is not `draft`/`rejected`/`superseded` must carry all four (`test_plans_frozen_is_bound`).
- `target_authorizations.justification` (10-2000 chars).
- `approvals_no_self_approval_high_risk`: a high/critical approval cannot be approved by its requester. Trigger `approvals_final`: a decided approval and its subject are immutable.
- Trigger `test_plans_guard`: contents of a non-draft plan are immutable; status moves only draft -> pending_approval|approved|superseded, pending_approval -> approved|rejected|superseded, approved|rejected -> superseded.
- Trigger `planned_tests_guard`: tests of a non-draft plan cannot be inserted, deleted or changed except for `status` (execution progress).
- Trigger `test_runs_plan_guard`: a run may only reference an **approved plan of the same project**, which is how a run is tied to the exact approved snapshot (the Stage 7 run-creation code must set `plan_id` to it and re-check the target gate in the worker).
Plan-level approvals only: `approvals.planned_test_id` is not used yet.

## Migration 0004 - break-glass grants (Stage 6 follow-up)
Additive: one table, `public.break_glass_grants (id, project_id, user_id, justification 20-2000 chars, created_at, expires_at, revoked_at, revoked_by)`. CHECKs: `expires_at > created_at` and at most 4 hours; revoke columns set together. Trigger `break_glass_guard`: the project, user, justification, window and an existing revocation cannot be changed - the only allowed update is revoking an open grant, so a grant can neither be extended nor rewritten. Expiry is evaluated with the database clock. Apply after 0003 with `alembic upgrade head` (review: `alembic upgrade 0003_plan_integrity:0004_break_glass --sql`). Not yet applied to the real database.

## Migration 0005 - job queue (Stage 7)
Additive. `test_batches`: `heartbeat_at`, `lease_expires_at` (for a claimed batch the worker's lease; for a queued batch with a `queue_task_id` the enqueue deadline), `not_before` (retry backoff); index `test_batches_lease_idx`. New table `test_batch_items (batch_id, run_id, planned_test_id, ordinal)`: PK `(batch_id, planned_test_id)`, `UNIQUE (batch_id, ordinal)`, `UNIQUE (run_id, planned_test_id)` (a test belongs to one batch of a run). The state machine, transition table, triggers, idempotency index, `test_results` uniqueness and `job_events` from 0002 are unchanged. Tested up/down on a disposable database; apply with `alembic upgrade head` after reviewing `alembic upgrade 0004_break_glass:0005_job_queue --sql`.

## Migration 0006 - test cases and the `not_run` state (Stage 9)
`test_results.status` gains `not_run` (a planned test that never started). New table `test_case_results (id, result_id -> test_results ON DELETE CASCADE, run_id -> test_runs ON DELETE CASCADE, ordinal, suite, classname, name 1-500 chars, status passed|failed|error|skipped, duration_ms >= 0, message <= 2000, detail <= 10000, created_at)` with `UNIQUE (result_id, ordinal)` and an index on `(run_id, status)`. Evidence uses the existing `artifacts` table (`kind` `log`/`report`, `run_id`, `result_id`). Downgrade drops the table and maps `not_run` back to `skipped`; round trip and constraints tested on a disposable database. Apply with `alembic upgrade head` after reviewing `alembic upgrade 0005_job_queue:0006_test_cases --sql`.

## Migration 0007 - scanner findings (Stage 10)
Additive columns on the existing `findings` family (see the Findings paragraph above): `findings.confidence` (CHECK low|medium|high, default `low`), `rule_id` (<=100), `file_path` (<=400), `line_number` (>0), `source_id` (FK `project_sources`), `limitations` (<=2000), `occurrences` (>=1, default 1), index `(project_id, source_id)`; `verification_attempts.method` (`rescan`|`manual`, default `manual`) and `evidence_artifact_id` (FK `artifacts`); `finding_events` CHECK widened with `reopened` and `verification_attempt`. Downgrade drops the columns and deletes the two new event types. The 0002 triggers still apply: `confirmed` needs a `finding_evidence` row, and `finding_events` is append-only. Tested up and down on a disposable database; **not applied to the real database**.

## Migration 0008 - normalized attributes and duplicate groups (Stage 10)
`findings` gains `cwe` (1..99999, nullable), `component` (<=400; `pypi:name@1.2` or `GET https://host/path`), `aliases` (`text[]`, <=20, default empty; advisory/CVE ids) and `group_id` (FK `finding_groups`, `ON DELETE SET NULL`); indexes `(project_id, group_id)` and a partial `(project_id, cwe)`. New table `finding_groups` (`project_id`, `group_key` unique per project, `kind` in `location`|`advisory`, timestamps). Groups are derived data recomputed after each scan (`services/dedup.py`); they never merge, hide or re-status findings. Existing rows stay valid (nullable/defaulted). Downgrade drops the columns and the table; findings are kept. Tested up and down on a disposable database; **not applied to the real database**.

## Pre-apply review of migrations 0003-0011 (2026-10-24; the owner reports they are now applied to the real database; kept as the review record and for other environments)
Reviewed by reading each migration and the rendered SQL (`alembic upgrade 0002_public_application_schema:0010_observability_alerts --sql`, 581 lines, no connection needed; 0011 was added later and tested the same way on a disposable database, but its SQL was not read through again line by line), and by the disposable-database tests (up, down and up again: `test_migrations.py`, 18 tests, plus the full suite). **Nothing was applied to the real database.** The real database was not inspected, so the preconditions below are *unverified there*.

**What they do to existing data**
- 0003 plan integrity: adds nullable columns and three CHECKs to `test_plans` / `approvals` (they validate existing rows), triggers on plans, planned tests, approvals and runs. No row is rewritten.
- 0004, 0005, 0008: new tables and nullable/defaulted columns, indexes. No row is rewritten.
- 0006: swaps the `test_results.status` CHECK for a wider one (adds `not_run`) and adds `test_case_results`.
- 0007: adds defaulted columns to `findings` / `verification_attempts`, widens the `finding_events` CHECK.
- 0009: new tables, defaulted columns on `llm_usage`; on `regression_tests` it adds columns, **backfills `project_id` and placeholder text from `findings` for existing rows** (the only data-writing statement in the range), then makes those columns NOT NULL and relaxes `finding_id`.
- 0010: new tables only, plus `regression_tests` gets two nullable columns, a widened subject CHECK and a replaced guard function. No row is rewritten.
- 0011 (added after the first review): `trace_id` NOT NULL columns with a volatile default on `test_runs` and `agent_runs` (**each table is rewritten once** and existing rows receive a trace id; an ACCESS EXCLUSIVE lock for the duration), indexes, the new table `ingest_event_ids`, an index on `events`, and a widened `alerts_rule_check`. Downgrade deletes alerts of the four new rules and drops the trace columns.

**What could stop an upgrade** (each migration runs in one transaction, so a failure aborts cleanly and leaves the database at the previous revision). Read-only pre-flight checks to run first:
```sql
-- expect revision 0002_public_application_schema
SELECT version_num FROM public.alembic_version;
-- 0003: existing rows that violate the new CHECKs (both expect 0)
SELECT count(*) FROM public.test_plans WHERE status NOT IN ('draft','rejected','superseded');
SELECT count(*) FROM public.approvals WHERE risk_level IN ('high','critical') AND decision = 'approved' AND decided_by = requested_by;
-- 0009: existing proposals (their project is taken from the finding); expect every row to have one
SELECT count(*) FROM public.regression_tests;
SELECT count(*) FROM public.regression_tests rt LEFT JOIN public.findings f ON f.id = rt.finding_id WHERE f.id IS NULL;
-- general: server version (gen_random_uuid needs 13+) and who owns the tables (run alembic as that role)
SHOW server_version;
SELECT tableowner FROM pg_tables WHERE schemaname = 'public' AND tablename = 'projects';
-- size of what the ALTERs will lock briefly
SELECT relname, n_live_tup FROM pg_stat_user_tables WHERE relname IN ('test_plans','approvals','test_results','findings','finding_events','regression_tests','llm_usage','test_batches') ORDER BY 1;
```
**Locks:** the `ALTER TABLE` statements take a short exclusive lock on `test_plans`, `approvals`, `test_results`, `findings`, `verification_attempts`, `finding_events`, `llm_usage`, `test_batches`, `regression_tests`, `target_authorizations`; on a small database this is milliseconds, but apply while no worker or API request is running (stop the API and Celery worker first).

**Downgrade is not harmless** (`alembic downgrade` removes data): 0010 drops the observability tables and deletes proposals drafted from alerts; 0009 drops `agent_runs`/`agent_steps`, the draft columns and deletes proposals drafted from a result; 0008 drops `finding_groups`; 0007 deletes `reopened`/`verification_attempt` finding events and drops finding columns; 0006 drops `test_case_results` and maps `not_run` to `skipped`; 0005/0004 drop their tables. Take a `pg_dump` first and prefer fixing forward.

**The exact commands, precautions and rehearsal evidence are in [`MIGRATION_RUNBOOK.md`](MIGRATION_RUNBOOK.md).** Earlier summary of the suggested procedure (the runbook supersedes it): `pg_dump` the real database; stop the API and worker; run the pre-flight queries above; `poetry run alembic upgrade 0002_public_application_schema:0011_trace_dedup_cost_alerts --sql > review.sql` and read it; `poetry run alembic current`; `poetry run alembic upgrade head`; `poetry run alembic current` (expect `0011_trace_dedup_cost_alerts`); start the app and check `GET /api/v1/health/ready`. Then, if wanted, enable `observability_ingest` on one test project only.

**Migration 0011 `0011_trace_dedup_cost_alerts` (Stage 12 completion, ADR-0011):** `test_runs.trace_id` and `agent_runs.trace_id` (32 lowercase hex, default random, indexed with the project); `ingest_event_ids (project_id, event_id, received_at)` for 24-hour event de-duplication; index `events_trace_idx`; `alerts_rule_check` widened with `llm_cost_spike`, `llm_runaway`, `llm_error_rate`, `run_duration_anomaly`. Written and tested (up, down, up) on a disposable database; **not applied to the real database**.
