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
**Findings:** `findings` (unique `(project_id, fingerprint)`; `severity`; `verification_state` unverified|likely|confirmed|not_reproduced|inconclusive; `status` new…reopened), `finding_events` (append-only), `finding_evidence` (finding ↔ artifact), `verification_attempts`, `regression_tests`.
**Artifacts:** `artifacts` (metadata + `storage_backend`/`storage_key`, `sha256`, `size_bytes`, `content_type`, validation/redaction status, `retention_until`, soft delete).
**Governance:** `policies` (global/project key→JSON; seeded safe defaults), `llm_usage` (tokens/cost per call, `blocked_by_budget`), `audit_events` (append-only).

**Deferred to later stages (no table yet, by design):** alerts/anomalies/trace references (Stage 12), chat history (Stage 14), report records (Stage 14), accessibility/LLM-security result detail beyond `test_results` + artifacts (Stages 9–13). Adding them requires a new migration and a doc update; no feature may assume them now.

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

