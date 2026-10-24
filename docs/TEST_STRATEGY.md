# Test Strategy

> Status: **Stage 2.** Tooling decided; database tests exist. Anything not run must be reported as "not run".

## Tooling (decided)
Backend: pytest, httpx/Starlette TestClient, Ruff, mypy (strict on `src/`). Frontend: Vitest + Testing Library (jsdom), oxlint; Playwright and axe-core for E2E/accessibility from Stage 5+. CI wiring is Stage 16.

## Layers
- **Backend unit:** services, permission/policy evaluation, state-transition helpers, parsers, redaction.
- **Database/migration integration (exists):** `backend/tests/integration/test_migrations.py` against a **disposable** PostgreSQL database named `*_test` (env `TEST_DATABASE_URL`; skipped if unset; refuses non-`_test` databases). Covers: upgrade/downgrade/re-upgrade, preservation of pre-existing tables and rows, foreign objects in `app_user` left in place on downgrade, run/batch state-machine enforcement, bounded retries, evidence-backed `confirmed` findings, append-only audit log, source URL guards, production authorization guard, high-risk approval floor.
- **API integration (Stage 4+):** each endpoint in API_DESIGN: success, validation (`422`), unauthenticated (`401`), forbidden (`403`), not-found-vs-inaccessible (`404`), CSRF, idempotency, rate limit, error envelope shape.
- **Authorization matrix tests (Stage 4):** table-driven over SECURITY_AND_SAFETY matrix × roles × project access levels; **user A cannot read/modify user B's projects, runs, findings, artifacts, or audit rows** for every child entity.
- **Jobs (Stage 7):** retry bounds, no auto-retry of destructive tests, cancel queued/running, timeout, duplicate delivery, worker-restart reconciliation.
- **Sandbox (Stage 8):** no secrets/Docker socket mounted, network denied, resource limits applied, ZIP attack fixtures, custom-script containment.
- **LLM/budget:** deterministic-first ordering, budget refusal, usage rows, prompt-injection fixtures (model text cannot widen scope).
- **Frontend:** component/utility; route/role UX; loading/error/empty/progress states; E2E and axe on key flows.
- **End-to-end:** intake (each of the four source types) → plan (each of three modes) → policy/approval → run → result → finding + evidence → regression → verify; production-blocked-by-default.

- **Observability (Stage 12):** `tests/unit/test_event_ingest_units.py` (fingerprints, event schema, redaction parity with the gateway redactor, hostile-input timing, thresholds, key format) and `tests/integration/test_observability.py` (key lifecycle and storage, off-by-default, identical 401s, cookies ignored, limits and drops, redaction in the database, grouping and sample caps, every alert rule, correlation, authorization matrix and audit, telemetry disclosure, internal alerts, alert-to-investigation/regression with the fake provider, retention); frontend `tests/alerts.test.jsx` plus axe cases.

## Running the database tests safely
Use a throw-away database (never the real one): create `sentinel_ai_test`, export `TEST_DATABASE_URL=postgresql://USER:PASS@HOST/sentinel_ai_test` from an untracked env file, then `cd backend && poetry run pytest`. The suite runs `alembic downgrade base` on that database.

## Model-assisted workflows (Stage 11)
Automated tests never call a real model: `FakeProvider` replays scripted answers and `FakeClock` drives deadlines, backoff and timeouts without sleeping. They cover redaction, evidence framing, budgets and audit, retries, deadline arithmetic, schema violations, citation checks, degraded outcomes, caching, authorization and the import boundaries. Prompt quality and real-provider behaviour (JSON mode, thinking tokens, latency) need an owner-approved real call and are not measured (Q104, Q110, Q115).

## Success measures
Baselines for blueprint §12 measures are undefined (Q22); set in Stage 15.
