# Migration runbook: checking and applying migrations 0003-0011 to the real database

Status 2026-10-24. The owner reports having applied migration 0011 (so 0003-0011) to the real database with `alembic current` at head and a passing health check (reported, not verified by Claude). **Claude ran nothing in this file against the real database**: it never read `backend/.env`, never contacted that database, and applies nothing without explicit authorization. The runbook was written beforehand and rehearsed on disposable PostgreSQL 17 databases (see "Rehearsal evidence"); it stays here for any other environment.

Repository head: `0011_trace_dedup_cost_alerts`. You reported only `0002_public_application_schema` applied; `alembic current` (step 1) is the authority. If it prints a later revision, start from that one in steps 5-6.

## Precautions (read first)
- **Never run the test suite with `TEST_DATABASE_URL` pointing at the real database.** The integration tests TRUNCATE tables and run `alembic downgrade base`. Check `echo "${TEST_DATABASE_URL:+set}"` is empty in the shell you use, and that its database name ends in `_test` whenever it is set.
- **Do not use `alembic downgrade` on real data.** Downgrades drop tables and delete rows (DATABASE_SCHEMA lists what). The way back is the backup in step 2.
- Each migration runs in **one transaction** (PostgreSQL transactional DDL). A failure rolls that migration back completely and leaves the previous revision in place (rehearsed).
- Apply **one revision at a time** with a lock timeout, so a blocked `ALTER TABLE` fails fast instead of queueing behind a long query and freezing the application.
- **Stop every writer first** (API, Celery worker, Celery beat). Migration 0011 rewrites `test_runs` and `agent_runs` once (adds a column with a volatile default); on a small database this is milliseconds, but it holds an exclusive lock.
- Do the real run in a quiet period, with the dump verified, and keep the terminal output.
- Secrets: never paste `DATABASE_URL` into chat, tickets or logs. The commands below read it from your environment or `backend/.env`.

## Steps (run from `backend/`)
1. **Where are we?**
   ```bash
   poetry run alembic current          # expect: 0002_public_application_schema   (alembic reads DATABASE_URL)
   poetry run alembic heads            # expect: 0011_trace_dedup_cost_alerts (head)
   ```
2. **Back up, then prove the backup is readable.**
   ```bash
   pg_dump --format=custom --no-owner --file "sentinel-ai-$(date +%F-%H%M).dump" "$DATABASE_URL"
   pg_restore --list "sentinel-ai-$(date +%F-%H%M).dump" | head          # must list tables, not error
   ```
   Best: restore it into a scratch database (`createdb sentinel_restore_check; pg_restore --no-owner -d sentinel_restore_check <dump>`) and run the pre-flight queries there first.
3. **Stop writers** (API, worker, beat) and look for open transactions:
   ```sql
   SELECT pid, state, xact_start, left(query, 60) FROM pg_stat_activity
   WHERE datname = current_database() AND pid <> pg_backend_pid() AND state <> 'idle';
   ```
4. **Pre-flight (read-only).** All must pass before step 6:
   ```sql
   SELECT version_num FROM public.alembic_version;                         -- 0002_public_application_schema
   SELECT count(*) FROM public.test_plans WHERE status NOT IN ('draft','rejected','superseded');             -- expect 0 (0003 would abort otherwise)
   SELECT count(*) FROM public.approvals WHERE risk_level IN ('high','critical') AND decision = 'approved' AND decided_by = requested_by;  -- expect 0
   SELECT count(*) FROM public.regression_tests rt LEFT JOIN public.findings f ON f.id = rt.finding_id WHERE f.id IS NULL;                 -- expect 0
   SHOW server_version;                                                      -- 13 or newer (gen_random_uuid)
   SELECT tableowner FROM pg_tables WHERE schemaname='public' AND tablename='projects';   -- run alembic as this role
   ```
   Save the row counts of every table for step 7 (`SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY 1;` is approximate; exact counts are better, see the rehearsal script in the tracker).
5. **Render and read the SQL** (no connection needed for this part; it only reads your revision):
   ```bash
   poetry run alembic upgrade 0002_public_application_schema:0011_trace_dedup_cost_alerts --sql > review.sql
   grep -nE '^(DROP|DELETE|TRUNCATE)|UPDATE public\.' review.sql     # expect only alembic_version updates and the 0009 regression_tests backfill
   ```
6. **Apply one revision at a time**, checking after each:
   ```bash
   export PGOPTIONS="-c lock_timeout=5s -c statement_timeout=120s"
   for rev in 0003_plan_integrity 0004_break_glass 0005_job_queue 0006_test_cases 0007_findings \
              0008_finding_groups 0009_llm_gateway_agent_runs 0010_observability_alerts 0011_trace_dedup_cost_alerts; do
     poetry run alembic upgrade "$rev" || { echo "STOPPED at $rev"; break; }
     poetry run alembic current
   done
   unset PGOPTIONS
   ```
   On failure the previous revision is still current and the data is untouched. Read the error, fix the data it names (for example the plan rows from step 4), and re-run that one revision. A `lock_timeout` error just means something held a lock: stop it and retry.
7. **Verify.** Compare exact row counts with step 4 (they must be equal: these migrations add no rows). Then `GET /api/v1/health/ready` (expects `migrations: ok`), start the API, the worker and beat, sign in, open a project's Alerts tab.
8. **Roll out the features gradually.** Event ingestion stays off per project until a manager turns it on; nothing is scheduled until beat runs; the purge job stays off until `EVENT_PURGE_ENABLED=true`; Redis-shared limits stay off until `RATE_LIMIT_BACKEND=redis`.

## If something goes wrong
- A migration failed: nothing was half-applied (rehearsed); fix and retry that revision.
- A migration succeeded but you must go back: restore the verified dump into a new database, point the application at it, and keep the failed one for inspection. Do not downgrade.

## Rehearsal evidence (2026-10-24, throwaway PostgreSQL 17, never the real database)
- A database was built at revision 0002 and seeded with one row in each of 11 tables (user, project, plan, planned test, approval, run, batch, result, finding, regression test, model usage). Upgrading **one revision at a time** with `PGOPTIONS='-c lock_timeout=5s -c statement_timeout=120s'` reached `0011_trace_dedup_cost_alerts (head)` with **all 11 row counts unchanged**; the existing regression test row received a project and placeholder text from 0009 (`(earlier proposal)`), and the existing run received a 32-hex trace id from 0011.
- A clone of the same database with one offending row (an `approved` plan without a content hash) failed at 0003 with `check constraint "test_plans_frozen_is_bound" ... is violated by some row`; `alembic current` still read `0002_public_application_schema`, the plan rows were intact and no 0003 column remained. The pre-flight query in step 4 returned 1 on that database and 0 on the clean one.
- The disposable-database test suite also runs up, down and up again over every revision (`tests/integration/test_migrations.py`).
- Not rehearsed: your real data volume and shapes, a different PostgreSQL version than 17, a database owned by a different role, concurrent traffic during the migration.
