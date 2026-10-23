# Sentinel AI — Project Tracker

Detailed progress record. The stage list, requirements and acceptance criteria are in [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md); product requirements are in the blueprint; unresolved questions are in [`OPEN_QUESTIONS.md`](OPEN_QUESTIONS.md); architecture decisions are in [`decisions/`](decisions/).

**Rule:** record only what was actually run and observed. State "not run" explicitly. A stage is Completed only when its acceptance criteria are met and recorded here.

## 1. Stage dashboard

| Stage | Name | Status | Detail |
|---|---|---|---|
| 0 | Confirm scope and decisions | Completed | Owner-confirmed scope (section 3); sign-off pending |
| 1 | Repository and Claude context | Completed | Section 4 |
| 2 | Architecture, data model, API contracts | Completed | Section 4; migrations applied to real DB per owner report (Q28) |
| 3 | Local services and configuration | Completed | Section 4; Redis deferred to Stage 7 |
| 4 | Authentication and RBAC (identity, roles, audit) | Completed | Authentication + RBAC done; project/membership routes delivered in Stage 5; approval-decision audit in Stage 6 |
| 5 | Project intake and deterministic analysis | Completed | ZIP upload + static analysis done; Git/localhost/remote registered, not analysed (Q36) |
| 6 | Test plans and approval policies | Completed | Section 7 (2026-10-22 Stage 6 entry); migration 0003 not yet applied to the real DB |
| 7 | Job queue, batches, cancellation, recovery | Completed | Section 7 (2026-10-23 Stage 7 entry); migrations 0003-0005 not yet applied to the real DB; uncommitted |
| 8 | Sandboxed execution foundation | Completed | Section 7 (2026-10-23 Stage 8 entry); uncommitted; no migration |
| 9 | First QA execution path | Completed | Section 7 (2026-10-24 Stage 9 entry); uncommitted; migration 0006 not applied to the real DB |
| 10 | Security integrations and finding verification | Completed (Bandit, dependency audit verified; Semgrep and ZAP integrated but not verified against the real tools: Q73, Q75) | Section 7 (Stage 10 entries); uncommitted; migrations 0007-0008 not applied to the real DB |
| 11 | LangGraph workflows and selective Gemini | Pending | Not started |
| 12 | Observability, alerts, failure-to-test loop | Pending | Not started |
| 13 | Accessibility, LLM/agent security, telemetry | Pending | Not started |
| 14 | Evidence-grounded chatbot, reporting, history | Pending | Not started |
| 15 | Regression verification and reliability | Pending | Not started |
| 16 | CI, Docker, deployment readiness, docs | Pending | Not started |

### Frontend track (separate from the stage list; Stage 11 stays paused)

| Phase | Scope | Status | Detail |
|---|---|---|---|
| F0 | Foundation (tokens, themes, router, navbar shell, shared components, status vocabulary, a11y harness) | Completed (owner approved by starting F1) | Section 7 (F0 entries), ADR-0009 |
| F1-F4 | Public site, sign-in and Request Access; auth and account; projects, overview, setup, analysis; test plans and approvals | Ongoing: implemented and checked, awaiting owner review | Section 7 (2026-10-23 F1-F4 entry) |
| F5-F9 | Runs and results report, findings, governance and admin, roadmap, hardening | Ongoing: implemented and checked, awaiting owner review | Section 7 (2026-10-23 F5 and F6-F9 entries) |

Owner review/commit state: Stages 0-5 are committed and pushed (owner report, 2026-10-22). Stage 6 is implemented but **uncommitted**.

## 2. Latest verified results (Stage 10 completion; latest run 2026-10-23: 592 passed, 4 skipped with DB + Docker, no Redis; see the Stage 10 completion entry in section 7)

Disposable PostgreSQL 17 (private cluster, port 55432), a throw-away `redis:7-alpine` container (127.0.0.1:56379, stopped afterwards) and the local Docker daemon (sandbox containers only, each test under its own scope label; 0 left). Nothing was run against the live `sentinel-ai` database, your dev Redis or `backend/.env`.

| Configuration | Result |
|---|---|
| DB + Redis + Docker | 503 passed (1 upstream httpx/starlette warning) |
| Docker present, no DB, no Redis | 336 passed, 167 skipped |
| Earlier in the stage: DB + Docker, no Redis | 497 passed, 4 skipped (real-broker tests) |
| `ruff check` / `ruff format --check` | clean (128 files; 2026-10-23 completion run) |
| `mypy` | clean (78 source files) |
| Frontend | `npm run lint` clean; `npm test` 34 passed (5 files; 10 new); `npm run build` ok |
| Stage 10 tests | unit 35 (`test_bandit_scanner.py`); integration 13 (`test_findings.py`: 10 DB-level incl. API/authorization, 3 real Bandit-in-Docker); migrations 2 (`test_migrations.py`); frontend 10 |
| Not re-run for Stage 10 | the "no Docker daemon" and "nothing available" configurations of Stage 9 (Docker tests skip by design; not re-measured) |
| Database changes | one migration, `0007_findings` (up and down tested on the disposable DB; **not applied to the real DB**, nor are 0003-0006) |

## 3. Decisions and scope (pointers and summaries)

- **Stack (ADR-0001, Accepted):** FastAPI, Celery + Redis, LangGraph, Gemini, Docker; React + Vite + JavaScript (no TypeScript); Python 3.12 + Poetry; PostgreSQL + Alembic.
- **Authentication (ADR-0002, Accepted in Stage 4):** email + password, Argon2id, server-side sessions with HMAC-hashed tokens, CSRF header + Origin allow-list, lockout and rate limiting; no SSO or bearer tokens in the first release.
- **Permission matrix:** `SECURITY_AND_SAFETY.md`; implemented in `backend/src/sentinel_ai/core/permissions.py`. Policy-dependent rows were deny-by-default until Stage 6; approvals now follow `services/policy.py` (Q27 resolved, ADR-0003).
- **Stage 5 scope decisions:** ZIP upload is the analysable source type; Git, localhost and remote-URL sources are registered and validated but not analysed; production remote targets are refused; raw `application/zip` upload instead of multipart (Q38); synchronous analysis returning 201 until Stage 7 (Q37).
- **Swagger local sign-in:** outside production the API's own origin is accepted by the Origin check; production accepts only `CORS_ALLOWED_ORIGINS`; the CSRF header is declared in OpenAPI.
- **First-release scope (confirmed 2026-10-22, moved here from the Stage 0 section of the plan):**

  - Application types: web apps, REST APIs, AI apps (RAG/agents).
  - Inputs: Git repository, ZIP upload, localhost URL, live development/staging URL.
  - Testing modes: automatic recommendations, prompt-based planning, developer-defined tests/scripts.
  - Excluded: MiroFish.
  - Requirements: evidence-backed findings; deterministic checks before LLM calls where practical, with cost limits; extensible testing-tool integrations; restricted execution for project code and custom scripts; production testing blocked by default unless explicitly authorized and approved.

## 4. Remaining work and known issues

- Stage 10 is implemented and **uncommitted** (Stages 0-9 are committed, HEAD 1c3fd06); Stage 11 is not started and needs owner go-ahead. Stage 6 follow-ups: Q40-Q46 in `OPEN_QUESTIONS.md`. Stage 7 follow-ups: Q52-Q57.
- Owner actions for Stages 6-9: review and commit; apply migrations 0003-0007 to the real database after reviewing `alembic upgrade 0002_public_application_schema:0007_findings --sql` (awaiting your approval; not done). Add the optional `JOB_*` variables (see `backend/README.md`) to `backend/.env.example` (outside Claude's permitted paths); none is required (defaults apply). The real Redis needs `REDIS_URL` with its password in `backend/.env`.
- Execution: `JOB_EXECUTOR=stub` is still the default (every test `skipped`, "Not executed"). `JOB_EXECUTOR=docker` is an explicit opt-in that runs only the fixed `sandbox_smoke` command in network-less containers; project code runs only if the operator opts in (Stage 9). Build the image first: `make -C backend sandbox-image` (now vendors pytest from the lock file; rebuild after Stage 9). Running a project's own tests (`pytest_unit`) is a further opt-in (`SANDBOX_ALLOW_PROJECT_CODE` + a stronger runtime or `SANDBOX_ACCEPT_SHARED_KERNEL=true`). Follow-ups: Q58-Q64 (Stage 8), Q65-Q72 (Stage 9). No new environment variables were added, so `.env`/`.env.example` need no change.
- Analysis of Git (needs sandboxed clone and credentials, Q25), localhost (Q26) and remote URL sources (needs target authorization, Stage 6, and sandbox, Stage 8) — Q36.
- Asynchronous analysis stays synchronous (Q37 deferred again, Q52); upload retention sweep (Q39); password reset and team routes (Q35); developer-visible user list (Q34); breach-corpus password check (Q33).
- Redis: Compose config verified and a Redis container was exercised in tests (Q32); your dev Redis was not touched. Readiness still does not require Redis (Q31).
- Frontend: no authentication or intake screens yet.
- Owner actions: commit Stages 4-5; add `SESSION_TOKEN_PEPPER` and the optional artifact/ZIP/login variables to `backend/.env` and `backend/.env.example` (the latter is outside Claude's permitted paths).
- Full list of open questions: `OPEN_QUESTIONS.md`.

## 5. Per-stage notes (moved verbatim from the former status lines in the plan)

**Stage 0 — Confirm scope and decisions**  
**Status:** DONE pending owner review (2026-10-22) — blueprint reviewed against ADR-0001; stack (Q14) and first-release scope (Q7) confirmed by the owner and recorded in ADR-0001 (now Accepted), OPEN_QUESTIONS and `settings.json`. Q15–Q24 are consciously deferred to Stage 2 or later. Celery+Redis and Docker isolation are chosen but not yet validated (Q6, Q8).

**Stage 1 — Repository and Claude context**  
**Status:** DONE pending owner review (2026-10-21) — acceptance criteria met by observed checks, see the progress log, section 7 of this file. Stage 0 decisions confirmed 2026-10-22; clean-clone verification done 2026-10-22 (the progress log, section 7 of this file). Awaiting owner sign-off.

**Stage 2 — Architecture, data model, API contracts**  
**Status:** DONE pending owner review (2026-10-22), with one open item: the migrations are verified on a disposable database but **not yet applied to the real `sentinel-ai` database** (see Q28). Owner confirmation of ADR-0002 / permission matrix (Q5, Q27) also pending. Evidence: the progress log, section 7 of this file.

**Stage 3 — Local services and configuration**  
**Status:** DONE (2026-10-22) — owner-reported live verification plus Claude's automated checks (the progress log, section 7 of this file). Redis is unavailable locally and is deliberately deferred to Stage 7.

**Stage 4 — Authentication and RBAC (identity, roles, audit)**  
**Status:** AUTHENTICATION + RBAC DONE pending owner review (2026-10-22); project ownership/membership routes and approval-decision auditing deferred to the stages that create those routes (see progress log)

**Stage 6 — Test plans and approval policies**  
**Status:** DONE pending owner review (2026-10-22); details in the progress log (section 7)

**Stage 5 — Project intake and deterministic analysis**  
**Status:** DONE pending owner review (2026-10-22): ZIP upload + static analysis; Git / localhost / remote-URL sources are registered and validated but not analysed (analysis depends on Stage 6 authorization and the Stage 8 sandbox; see Q36)

## 6. Progress update template

Append a new entry to the progress log after meaningful work, then update the dashboard above and the stage's status and next action in `IMPLEMENTATION_PLAN.md`.

Append or update this section after meaningful work:

```text
Date:
Stage:
Status: NOT STARTED / IN PROGRESS / BLOCKED / DONE / DEFERRED
Changes made:
Files changed:
Commands actually run:
Test results:
Acceptance criteria met:
Known issues:
Decisions made or changed:
Next action:
```

Keep one current status per stage; use Git history and decision records for detailed historical changes.

## 7. Progress log (chronological; moved verbatim from section 21 of the plan)

```text
Date: 2026-10-21
Stage: 0 and 1 (documentation setup only)
Status: Stage 0 IN PROGRESS; Stage 1 IN PROGRESS (historical entry; superseded by later entries)
Changes made: Created instruction files, settings, .gitignore, architecture/doc skeletons, ADR-0001 (Proposed), OPEN_QUESTIONS. Blueprint added to docs/ (byte-identical to Downloads/Sentinel_AI_Full_Project_Blueprint_Updated.md). This file replaced with the complete plan (byte-identical copy of Sentinel_AI_IMPLEMENTATION_PLAN.md) plus status edits and this log. Removed redundant Sentinel_AI_Project_Overview.md.
Commands actually run: file listing, cmp/md5sum comparisons, cp, rm of the overview, JSON validation of settings.
Test results: none; no code exists.
Acceptance criteria met: none fully.
Known issues: see docs/OPEN_QUESTIONS.md.
Decisions made or changed: none.
Next action: resolve Q9 (tool/version choices) and Q12 (git init), then begin Stage 1 project init on approval.
```

```text
Date: 2026-10-21
Stage: 1 — Initialize repository and Claude context
Status: DONE pending owner review (Stage 0 still IN PROGRESS)
Changes made: git init -b main (no commits). Blueprint reviewed vs ADR-0001/skeletons -> OPEN_QUESTIONS Q14-Q24. Backend: Poetry project (Python 3.12), FastAPI app with GET /api/v1/health, pytest test, Ruff/mypy config, Alembic initialized in backend/migrations (no schema, empty sqlalchemy.url), .env.example, README. Frontend: Vite + React scaffold (originally TS; converted to JavaScript, see amendment entry below) with a static heading, Vitest + Testing Library test, .env.example, README. Updated CLAUDE.md commands, root README, settings.json stage, ADR-0001 addendum.
Files changed: backend/**, frontend/**, README.md, settings.json, docs/OPEN_QUESTIONS.md, docs/decisions/ADR-0001-*.md, docs/IMPLEMENTATION_PLAN.md, backend/CLAUDE.md, frontend/CLAUDE.md.
Commands actually run: poetry install; poetry run pytest / ruff check / ruff format --check / mypy / alembic --help; npm install; npm run lint / test / build.
Test results: backend pytest 1 passed (1 upstream deprecation warning); ruff check and format clean; mypy strict clean (4 files); alembic CLI runs. Frontend oxlint exit 0; vitest 1 passed; build succeeded. NOT run: dev servers, uvicorn live request, Docker, any CI.
Acceptance criteria met: frontend/backend separate; scoped instructions exist; no secrets committed (placeholders only); hello-world checks pass; commands documented. Not verified: reproducibility from a clean checkout (no clean-clone test done).
Known issues: Q14-Q24 in OPEN_QUESTIONS; frontend/backend Dockerfiles, docker-compose and CI intentionally deferred to Stages 3/16.
Decisions made or changed: toolchain confirmed (ADR-0001 addendum); oxlint kept as Vite template default.
Next action: owner review; resolve Q14/Q15/Q7; then Stage 2 (not started).
```

```text
Date: 2026-10-21
Stage: 1 (amendment)
Changes made: Frontend converted from TypeScript to JavaScript per owner request (removed tsconfig*, typescript and @types/*; files renamed to .jsx/.js; build script now `vite build`). Docs updated (frontend CLAUDE.md/README, ADR-0001 addendum, this plan).
Test results: superseded by the verification entry below (the original "re-run (see report)" had no recorded results).
```

```text
Date: 2026-10-22
Stage: 1 (verification after JavaScript conversion)
Status: DONE pending owner review (Stage 0 still IN PROGRESS)
Changes made: docs only. frontend/README.md build comment corrected (no type-check); plan file tree main.tsx -> main.jsx; stale TS/"see report" wording in earlier log entries annotated.
Commands actually run: frontend: npm run lint; npm test; npm run build. backend: poetry run pytest; ruff check .; ruff format --check .; mypy; alembic --help.
Test results: frontend oxlint exit 0; vitest 1 file / 1 test passed; vite build succeeded (16 modules, dist/ emitted). backend pytest 1 passed, 1 warning (starlette/httpx deprecation, Q23); ruff check clean; ruff format 8 files already formatted; mypy no issues in 4 source files; alembic CLI prints usage.
NOT run: dev servers, live uvicorn request, Docker, CI, clean-clone reproducibility test, git commit (none made; awaiting owner approval).
Acceptance criteria: separate frontend/backend - met; root and scoped instructions - met; no secrets committed - met (placeholders only, no commits exist); hello-world checks - met (tests/build/lint above); setup commands documented - met. Reproducibility from a clean checkout - NOT verified.
Known issues: Q14/Q7 open (Stage 0); Q23 warning.
Next action: owner decides on initial commit and clean-clone test; owner review/sign-off.
```

```text
Date: 2026-10-22
Stage: 1 (repository verification)
Status: DONE pending owner review (Stage 0 still IN PROGRESS)
Changes made: tracker only.
Commands actually run: git status -sb; git log; git remote -v; git branch -vv; git ls-remote origin; git ls-files filtered for .env/node_modules/.venv/dist/caches.
Results: branch main tracks origin/main (git@github.com:Vinay-Ampera/Sentinel-AI.git) at b55c582 "chore: initialize Sentinel AI project structure", the only commit; working tree clean; ls-remote returns the same hash; 44 tracked files, none are .env, node_modules, .venv, dist or tool caches.
NOT run: clean-clone reproducibility test (not yet done, still the one unverified Stage 1 criterion); CI (none configured).
Next action: owner approval for a clean-clone test; owner decisions on Q7 and Q14.
```

```text
Date: 2026-10-22
Stage: 0 (decisions) and 1 (clean-clone verification)
Status: Stage 0 DONE pending owner review; Stage 1 DONE pending owner review
Changes made: ADR-0001 -> Accepted with 2026-10-22 addendum (stack, scope, inputs, testing modes, MiroFish excluded, five requirements). OPEN_QUESTIONS: Q7 and Q14 resolved, Q18 note, decisions section and Stage 2 follow-ups. IMPLEMENTATION_PLAN: Stage 0/1 status and first-release scope. settings.json: supported_application_types, supported_inputs, testing_modes, exclusions, decisions_pending. Docs/config only; no application code changed.
Commands actually run: git clone git@github.com:Vinay-Ampera/Sentinel-AI.git into the session scratchpad (commit b55c582); backend: poetry install (in-project venv), pytest, ruff check, ruff format --check, mypy; frontend: npm ci, npm run lint, npm test, npm run build.
Test results (clean clone): pytest 1 passed, 1 warning (Q23); ruff clean; ruff format 8 files already formatted; mypy no issues in 4 files; npm ci 0 vulnerabilities; oxlint exit 0; vitest 1 file / 1 test passed; vite build succeeded.
NOT run: live uvicorn/dev-server request (command was denied by the permission prompt), Docker, CI. The clone verifies the committed state b55c582 only; the doc edits above are uncommitted.
Acceptance criteria (Stage 1): all met, including reproducible setup from a clean checkout (README commands for install, lint, test, build worked as written, with Poetry in-project venv for the backend).
Known issues: Q6/Q8 unvalidated; Q15-Q24 deferred; no CI; no live-server check.
Next action: owner reviews and commits these doc changes; sign-off on Stage 0/1; Stage 2 not started.
```

```text
Date: 2026-10-22
Stage: 2 — Architecture, data model, and API contracts
Status: DONE pending owner review; real-database apply NOT done
Changes made: Alembic env.py now reads DATABASE_URL from the environment only (psycopg 3). Added deps sqlalchemy>=2.0 and psycopg[binary]>=3.2 (poetry.lock updated). Migrations 0001_app_user_schema (roles, users, sessions, password_reset_tokens) and 0002_public_application_schema (24 tables: teams, memberships, projects, sources, target_authorizations, analysis_snapshots, plans, planned_tests, approvals, runs, batches, results, job_events, findings + events/evidence/verification/regression, artifacts, llm_usage, policies, audit_events, state_transitions) with DB-enforced rules (state machine, evidence-backed findings, append-only audit, production authorization guard, source URL guards). Tests: backend/tests/integration/test_migrations.py (8 tests, need disposable TEST_DATABASE_URL ending _test). Docs rewritten: DATABASE_SCHEMA, SYSTEM_ARCHITECTURE, API_DESIGN, JOB_AND_SANDBOX_DESIGN, SECURITY_AND_SAFETY, TEST_STRATEGY, FILE_STRUCTURE; new ADR-0002 (Proposed); backend .env.example/README/CLAUDE.md; OPEN_QUESTIONS Q25-Q30; settings.json.
Commands actually run: initdb + temporary PostgreSQL 17 server on a unix socket (/tmp/sai_pg, data in session scratchpad) with database sentinel_ai_test; poetry add; alembic upgrade head / downgrade base / upgrade head --sql; pytest (with and without TEST_DATABASE_URL); ruff check; ruff format --check; mypy; psql probes on the disposable DB only.
Results: upgrade head from empty DB succeeded; downgrade base succeeded; re-upgrade succeeded. pytest with TEST_DATABASE_URL: 9 passed (1 health + 8 DB tests), 1 upstream warning. Without it: 1 passed, 8 skipped. ruff check clean; ruff format clean (11 files); mypy no issues (4 files). Pre-existing tables/rows (public.legacy_probe) survived upgrade, downgrade and re-upgrade. Manual test: creating a conflicting public.teams table with a row then running upgrade failed with DuplicateTable, rolled back atomically (no app_user schema, no new tables) and left the row intact. Offline `upgrade head --sql` emits 29 CREATE TABLE statements. Missing DATABASE_URL gives a clear error.
NOT run: anything against the real sentinel-ai database (backend/.env is blocked from Claude by a deny rule and no credentials were available or requested; role "vinayrepalle" does not exist on the local server). Existing schemas/tables of sentinel-ai were therefore NOT inspected. No API endpoints, models, auth code, Docker, Redis, Celery, or frontend changes. Frontend checks not rerun (no frontend change). Nothing committed or pushed.
Acceptance criteria: DATABASE_SCHEMA agrees with API/workflow docs (cross-checked: entity/status names, source types, approval and production rules) - met by review, not by automated check; project ownership/access scope explicit (DATABASE_SCHEMA, SECURITY_AND_SAFETY) - met; migrations create the schema from an empty database - met on the disposable DB, not yet on the real DB; no feature depends on undocumented schema (deferred tables listed) - met.
Known issues: Q5/Q27 confirmation; Q25, Q26, Q28-Q30 new; retention/production store undecided; alerts/chat/report tables intentionally deferred; Argon2 dependency deferred to Stage 4.
Next action: owner inspects the real database and applies the migrations (commands in docs/DATABASE_SCHEMA.md), confirms ADR-0002, reviews and commits. Stage 3 not started.
```

```text
Date: 2026-10-22
Stage: 2 (finalization)
Status: DONE pending owner review; real-database apply still NOT done (by instruction)
Changes made: backend/.env.example rewritten with every Stage 2 variable, each labelled [NOW] (DATABASE_URL, TEST_DATABASE_URL) or [LATER: Stage N], placeholders only. backend/.env was not read or modified. Stage 2 status line unchanged.
Commands actually run: script comparing CREATE TABLE names in the two migrations with DATABASE_SCHEMA.md; restarted the disposable PostgreSQL 17 server (/tmp/sai_pg, database sentinel_ai_test) and stopped it afterwards; pytest with TEST_DATABASE_URL; ruff check; ruff format --check; mypy; alembic upgrade head and current on the disposable DB.
Results: 28 tables in migrations (4 app_user + 24 public), all named in DATABASE_SCHEMA.md; pytest 9 passed (1 upstream warning); ruff clean; format clean (11 files); mypy clean (4 files); alembic current = 0002_public_application_schema (head); information_schema shows app_user 4 tables, public 24 + alembic_version. .gitignore: .env.* ignored, .env.example not ignored and tracked.
NOT run: anything against the real sentinel-ai database; no new database created.
Acceptance criteria: all four met on the disposable database (see Stage 2 section). "Migrations create the schema from an empty database" is proven on the disposable DB only.
```

```text
Date: 2026-10-22
Stage: 2 (owner-reported real-database apply)
Status: Stage 2 DONE pending owner review
Report (from the project owner; NOT independently verified by Claude, who has no access to the real database): alembic migrations were applied to the existing local sentinel-ai database; 28 tables created (4 in app_user, 24 in public) and the owner's migration/verification commands completed successfully. Exact command output was not provided.
Claude's own evidence remains the disposable-database results above.
Next action: owner sign-off and commit. Stage 3 not started.
```

```text
Date: 2026-10-22
Stage: 3 — Local development services and configuration
Status: DONE pending owner review
Already present before the continuation (written in the interrupted session): dependencies pydantic-settings and redis; core/config.py (Settings, DatabaseSettings, ConfigError, value-free validation errors, production rules); core/logging.py (URL-password redaction); core/health.py (database, migration, redis probes returning status words only); db/engine.py (engine + session factory).
Newly implemented in the continuation: migrations/env.py now loads DATABASE_URL through DatabaseSettings (env, then backend/.env; SystemExit with a value-free message on error); core/errors.py (error envelope handlers); core/middleware.py (request ID + security headers); api/health.py (/health, /health/live, /health/ready, 200/503); main.py application factory create_app(settings) with lifespan, CORS allow-list, lazy engine (run with `uvicorn sentinel_ai.main:create_app --factory`); docker-compose.yml (Redis; optional separate PostgreSQL under profile local-db; no default passwords; ports bound to 127.0.0.1); root .env.example; backend/Makefile (lint, format-check, typecheck, test, check, migrate targets); backend/.env.example relabelled [NOW]/[LATER] with SENTINEL_ENV_FILE, DB_*, REDIS_*; tests: tests/unit/test_config.py, tests/unit/test_api_foundation.py, updated tests/unit/test_health.py, and 3 more tests in tests/integration/test_migrations.py (probes and /health/ready against the disposable DB); docs: backend README/CLAUDE.md, root README, FILE_STRUCTURE.
Commands actually run: pytest (with and without TEST_DATABASE_URL), make check, ruff check, ruff format --check, mypy, docker compose config (validation only), frontend npm run lint/test/build, temporary PostgreSQL 17 on a unix socket for the disposable database (stopped afterwards).
Results: with the disposable DB: pytest 36 passed (1 upstream warning); without it: 26 passed, 10 skipped (DB tests skip by design); ruff check clean; ruff format clean (21 files); mypy no issues (12 source files); `make check` passed end to end. Compose: `docker compose config` fails with a clear message when REDIS_PASSWORD is unset, validates with REDIS_PASSWORD only (services: redis) and with the local-db profile (redis, postgres). Frontend: lint exit 0, vitest 1 passed, build succeeded (unchanged code, rerun for completeness).
Acceptance criteria: (1) Services start from documented commands - Compose file and commands documented and config-validated; containers were NOT started (would pull images), so actual startup is not verified. (2) Secrets environment-supplied and not committed - met: SecretStr, no defaults for passwords, only .env.example files tracked, .env ignored. (3) Backend can connect to the database and run migrations - met on the disposable database (probes, upgrade/downgrade, /health/ready end to end); NOT run against the real sentinel-ai database by Claude. (4) Health/readiness work without exposing sensitive values - met (tests assert no user, password, host or database name in responses).
NOT run: uvicorn as a live server; docker compose up; anything against the real sentinel-ai database. Claude never connected to sentinel-ai in Stage 3, and ran no DDL/DML anywhere except the disposable database; the existing sentinel-ai tables were not touched (owner-reported state: 28 tables).
Owner-side verification (safe, read-only): cd backend && poetry run alembic current   # expect 0002_public_application_schema (head); then start the API and GET /api/v1/health/ready (expect database ok, migrations ok).
Known issues: Q31 below; Redis does not yet fail readiness (deliberate until Stage 7).
Next action: owner review/commit; Stage 4 not started.
```

```text
Date: 2026-10-22
Stage: 3 (final verification)
Status: DONE
Owner-reported live verification (project owner; Claude has no access to the real database or running servers and did not observe these): backend, frontend, the sentinel-ai database, Alembic migrations, and the health endpoints all work when run live. Redis is currently unavailable on the owner's machine; per the owner it will be addressed in Stage 7. Exact command output was not provided.
Claude-run checks (this session): with a disposable PostgreSQL database, `make check` passed: pytest 36 passed (1 upstream warning), ruff check clean, ruff format clean (21 files), mypy no issues (12 source files). Frontend: lint exit 0, vitest 1 passed, vite build succeeded. Disposable server stopped afterwards.
Decisions: Q31 resolved - Redis stays reported-but-not-required in /health/ready until Stage 7 (consistent with the owner's report: readiness is not blocked by the missing Redis). Q32 narrowed - Compose Redis/PostgreSQL services are config-validated only; actually starting them is deferred with Redis to Stage 7.
Acceptance criteria: (1) Services start from documented commands - met for backend, frontend and PostgreSQL (owner-reported); the Redis service is the documented exception, deferred to Stage 7 by owner decision. (2) Secrets environment-supplied and not committed - met. (3) Backend connects to the database and runs migrations - met (owner-reported live on sentinel-ai; Claude-verified on the disposable database). (4) Health/readiness without exposing sensitive values - met (tests; owner-reported live endpoints work).
NOT run by Claude: live servers, docker compose up, anything against sentinel-ai.
Next action: owner review/commit; Stage 4 not started.
```

```text
Date: 2026-10-22
Stage: 4 — Authentication and role-based access control (scope requested by the owner: authentication and authorization only)
Status: authentication + RBAC DONE pending owner review. NOT done by design: project CRUD/membership routes (Stage 5), approval-decision audit (Stage 6), frontend login UI.
Implemented (ADR-0002, now Accepted): Argon2id password hashing (argon2-cffi added) with policy (12-128 chars, repetition/common-list/email-name checks); server-side sessions in app_user.sessions (256-bit token in HttpOnly SameSite=Lax cookie, only an HMAC-SHA-256 keyed with SESSION_TOKEN_PEPPER stored, new token every login, idle + absolute expiry, revocation); CSRF (per-session token re-derivable for GET /auth/me, X-CSRF-Token + Origin allow-list on POST/PUT/PATCH/DELETE); per-account lockout (LOGIN_MAX_FAILURES / LOGIN_LOCKOUT_MINUTES) with uniform 401s and dummy-hash timing equalisation; per-IP login rate limit (in-process); endpoints POST /auth/login, /auth/logout, GET /auth/me, POST /auth/password (revokes other sessions), GET/DELETE /auth/sessions; GET /users, POST /admin/users, PATCH /admin/users/{id} with the documented Admin-vs-Super-Admin rules, self-change prohibition, last-Super-Admin guard, session revocation on role change/deactivation; permission matrix as code (core/permissions.py); project access resolver (owner / membership / team access / team owner; Super Admin all; Admin no implicit access; unknown and inaccessible both 404) and route guard require_project_access; audit rows (auth.login/logout/lockout/password_change/session_revoke, user.create/update/bootstrap_super_admin, authz.denied) with redaction; operator command `python -m sentinel_ai.cli create-super-admin` (password from prompt). No migration was needed: the existing app_user/audit schema is used unchanged.
Changed/added files: backend/src/sentinel_ai/{core/security.py, core/permissions.py, core/ratelimit.py, core/errors.py (DomainError), core/config.py (login_ip_max_attempts_per_minute, pepper()), repositories/identity.py, repositories/project_access.py, services/{audit,auth,users,project_access}.py, schemas/identity.py, api/{deps,auth,admin}.py, cli.py, main.py}; backend/pyproject.toml + poetry.lock (argon2-cffi, ruff B008 setting, pytest path); tests/support.py, tests/unit/{test_security_primitives,test_auth_unauthenticated}.py, tests/integration/{conftest,test_auth_api,test_authorization}.py; docs.
Commands actually run (backend/): pytest with a disposable PostgreSQL 17 (database sentinel_ai_test) and without it; ruff check; ruff format --check; mypy.
Results: with the disposable DB 78 passed (1 upstream httpx/starlette warning); without it 38 passed, 40 skipped (DB tests skip by design); ruff clean; format clean (44 files); mypy clean (29 source files).
NOT run: anything against the real sentinel-ai database (no user created there); a live uvicorn session or browser login; backend/.env was not read or modified (access denied), so SESSION_TOKEN_PEPPER presence in it is unverified.
Acceptance criteria: (1) Backend enforces permissions on every protected route - met for all routes that exist; test_all_non_public_routes_require_a_session walks the OpenAPI schema and asserts 401 for each non-public route. (2) UI role controls are not the only check - met (server-side only; no UI yet). (3) Unauthorized users cannot read projects/runs/artifacts/findings - guard and cross-project/cross-role tests are done; those routes do not exist yet, so each Stage 5-10 route must use require_project_access (tested through a throw-away probe router). (4) Sensitive actions are auditable - met for authentication and user administration; membership changes and approval decisions must write audit rows when built.
Known issues / owner actions: (a) add SESSION_TOKEN_PEPPER (>= 32 random chars, e.g. `python -c "import secrets;print(secrets.token_urlsafe(48))"`) and optionally LOGIN_IP_MAX_ATTEMPTS_PER_MINUTE to backend/.env; I could not edit backend/.env.example, which should also gain LOGIN_IP_MAX_ATTEMPTS_PER_MINUTE; (b) create the first Super Admin: `cd backend && poetry run python -m sentinel_ai.cli create-super-admin --email ... --display-name ...`; (c) Q33-Q35 in OPEN_QUESTIONS.
Next action: owner review/commit. Stage 5 not started.
```

```text
Date: 2026-10-22
Stage: 5 — Project intake and deterministic analysis
Status: DONE for the ZIP-upload source type, pending owner review. NOT done: Git repository, localhost URL and remote URL sources (Q36); analysis of anything other than an uploaded ZIP; frontend screens; asynchronous (202) analysis.
Scope decisions: (1) ZIP upload is the initial input method because it needs no network and no process execution. Git (clone = network + hooks/credentials), localhost URL (sandbox reachability, Q26) and remote URL (target authorization/SSRF) need Stage 6/8 machinery and are recorded, not half-built. (2) Stage 4 deferred project CRUD and membership to the stages that need them; Stage 5's ownership criterion needs them, so they are included. (3) The upload is the raw request body (Content-Type: application/zip), not multipart, because python-multipart could not be installed (no network); this also lets the size cap be enforced while streaming. (4) Analysis runs synchronously inside the request (static parsing only, nothing executed or extracted) and returns 201 instead of the designed 202; the job queue arrives in Stage 7.
Implemented: projects (create / list / get / edit / archive; creator becomes owner; archived projects are read-only); membership (GET/PUT/DELETE, read < run < manage); ZIP source registration POST /projects/{id}/sources/zip?name=; source list / deactivate; analyses POST /projects/{id}/analyses {source_id}, GET list, GET /analyses/{id}. Archive validation (services/archive.py): size cap enforced while streaming, ZIP magic, entry-count and total-uncompressed caps, compression-ratio (bomb) check, rejects traversal/absolute/backslash/drive/control-character/bidi names, over-deep or over-long paths, symlinks and special files, encrypted entries, non-stored/deflated compression, duplicate and case-folded duplicate names; error messages never echo entry names; archives are never extracted and nothing from them is executed. Storage (services/artifact_store.py): server-generated keys, root-escape and symlink-escape refusal, file mode 0640, artifacts row with SHA-256, hash re-verified before every analysis. Analyzer (services/analyzer.py, version 1.0.0): detects languages, frameworks, test tools, coverage tools, test files, lockfiles, config files (Docker, CI, OpenAPI, ...) and package scripts from file names and bounded manifest reads (package.json, requirements*.txt, pyproject.toml, go.mod, pom.xml, build.gradle, Gemfile, composer.json); output has separate `facts` (with evidence paths), `inferences` (confidence + basis), `gaps` (unavailable evidence and coverage gaps) and `warnings`; .env/key-like files are flagged by name only, contents never read or stored; output is a pure, sorted function of the bytes, so repeating an analysis gives an identical result. Authorization: role permission (new SOURCE_MANAGE, PROJECT_ANALYZE) AND project access level on every route (read: view; run: analyse; manage: edit, members, sources, upload); unknown and inaccessible projects/sources/analyses are indistinguishable 404s; child ids are always looked up with project_id; Admin has no implicit access; Super Admin access without an own grant writes project.privileged_access, and listing all projects writes project.list_all. Audit: project.create/update/archive/member_set/member_remove, source.create/upload (failure with reason)/deactivate, analysis.run, project.privileged_access.
Database changes: NONE. No migration; existing public.projects, project_memberships, artifacts, project_sources and analysis_snapshots are used as designed (analysis output is stored in analysis_snapshots.detected, content hash in content_sha256). The real sentinel-ai database was not touched.
Changed/added: backend/src/sentinel_ai/{services/archive.py, services/analyzer.py, services/artifact_store.py, services/projects.py, services/project_access.py (+is_privileged_only), repositories/projects.py, schemas/projects.py, api/projects.py, api/deps.py (privileged-access audit), core/permissions.py, core/config.py (artifact_root), main.py}; pyproject.toml (per-file E501 exemption for analyzer data tables); tests: tests/unit/{test_archive_validation,test_analyzer,test_artifact_store}.py, tests/integration/test_projects_api.py, helpers in tests/support.py, header-copy fix in tests/integration/conftest.py; docs.
Commands actually run (backend/): pytest with a disposable PostgreSQL 17 (database sentinel_ai_test) and without it; ruff check; ruff format --check; mypy.
Results: with the disposable DB 146 passed (1 upstream httpx warning); without it 81 passed, 65 skipped (DB tests skip by design); ruff clean; format clean (55 files); mypy clean (36 source files). These are DISPOSABLE-DATABASE results only; nothing was verified against the live sentinel-ai database, a running server, or a browser.
Defects found and fixed while testing: the validator wrongly rejected ZIPs whose Unix mode has no file-type bits (as written by Python's zipfile); a test helper mutated shared headers (test-only).
Acceptance criteria: (1) Facts distinguished from inferences - met (separate sections, evidence vs basis/confidence; tested). (2) Invalid or oversized input rejected safely - met for ZIP uploads (tested: not-a-zip, truncated, traversal, absolute path, empty, bomb, too many files, oversize by header and while streaming, wrong content type, control characters; no file or row left behind; failures audited). (3) Project/source ownership enforced - met (cross-user, cross-project-child, membership-level, Admin, Super Admin tests). (4) Repeatable analysis persisted and visible - met (identical result on re-run, stored in analysis_snapshots, readable via API). The sub-items "Git/URL input types" are explicitly incremental per the plan and remain open.
Known issues / owner actions: Q36-Q38 in OPEN_QUESTIONS. Optionally set ARTIFACT_STORAGE_DIR (default backend/artifacts, git-ignored), UPLOAD_MAX_MB (100), ZIP_MAX_UNCOMPRESSED_MB (500), ZIP_MAX_FILES (20000).
Next action: owner review/commit. Stage 6 not started.
```

```text
Date: 2026-10-22
Stage: 5 (completion)
Status: DONE pending owner review. Remaining Stage 5 items implemented; items that depend on later stages are documented, not built.
Implemented now: POST /projects/{id}/sources (JSON) for git_repository {git_url, git_ref?}, localhost_url {target_url} and remote_url {target_url, environment}. Validation (services/source_validation.py, pure functions, no DNS or network): Git URLs must be public https:// with no credentials, no query/fragment, default port, repository path; refs must be plain branch/tag names (cannot start with '-', no '..', '@{', spaces, shell characters); localhost URLs must be exactly localhost / 127.0.0.1 / [::1]; remote URLs must be public http(s) dev or staging hosts. All sources reject credentials, private/loopback/link-local/metadata IPs (including IPv4-mapped IPv6 and decimal/hex IPv4 tricks), single-label and internal-looking names (.local, .internal, .cluster.local, ...), control characters and over-long URLs. Production remote targets are refused (production_blocked, audited as denied) because production testing is blocked by default. Registration writes only a project_sources row (the existing CHECK constraints agree with the validators); nothing is fetched, cloned, resolved or probed, and no target_authorization is created. Analysing these source types returns 422 analysis_not_available with the reason and creates no snapshot (no invented results). Also: stale upload temp files are purged at startup and by `python -m sentinel_ai.cli purge-temp`.
Open questions reviewed: Q36 narrowed (registration done; analysis of Git needs a sandboxed clone + Q25 credentials, localhost needs Q26, remote needs Stage 6 authorization + Stage 8 sandbox with DNS re-resolution at use time); Q37 deferred to Stage 7 (needs the job queue); Q38 decided: keep the raw application/zip upload, no multipart dependency unless the frontend needs it; Q39 temp-file half resolved, retention sweep deferred (needs run history from Stage 7+).
Database changes: NONE (no migration; existing project_sources columns and CHECKs used).
Changed/added: services/source_validation.py (new), services/projects.py (register_url_source, analysis_not_available), services/artifact_store.py (purge_stale_temp), repositories/projects.py, schemas/projects.py, api/projects.py, main.py (startup purge), cli.py (purge-temp); tests: tests/unit/test_source_validation.py, additions to tests/unit/test_artifact_store.py and tests/integration/test_projects_api.py.
Commands actually run (backend/): pytest with a disposable PostgreSQL 17 (database sentinel_ai_test) and without it; ruff check; ruff format --check; mypy.
Results (DISPOSABLE database only; nothing run against the live sentinel-ai database, a live server, or a browser): 184 passed (1 upstream httpx warning); without the database 116 passed, 68 skipped; ruff clean; format clean (57 files); mypy clean (37 source files).
Acceptance criteria: unchanged from the earlier Stage 5 entry and still met: facts vs inferences; invalid/oversized input rejected safely (now also for Git/URL descriptors, tested incl. SSRF-style hosts and a no-network assertion); ownership enforced (access-level and cross-user tests also cover URL sources); repeatable persisted analysis (ZIP).
Not done / depends on later stages: analysis of Git / localhost / remote sources; target_authorizations and approval (Stage 6); sandboxed clone and probing (Stage 8); credentials for private repositories (Q25); async analysis (Q37); frontend intake screens; team_id on project creation (teams have no routes yet).
Owner actions: add the .env lines listed in the report (backend/.env.example is outside what Claude may read or edit in this environment, so it was NOT updated by Claude).
Next action: owner review and commit of Stages 4-5. Stage 6 not started.
```

```text
Date: 2026-10-22
Stage: tracking restructure (documentation only)
Status: no stage status changed
Changes made: IMPLEMENTATION_PLAN.md reduced to stage list with status (Pending / Ongoing / Completed), next action, requirements and acceptance criteria; the long per-stage status text, the Stage 0 first-release scope block, the progress-update template and the progress log were moved here without loss. CLAUDE.md files keep permanent instructions only; README status lines point to this file.
Application code: not modified. Stage 6: not started.
```

```text
Date: 2026-10-22
Stage: 6 — Test plans and approval policies
Status: DONE pending owner review. Not done: running anything (Stages 7-10), frontend screens beyond sign-in / plan list / plan review, a revise-after-submit flow (create a new version instead), per-test approvals.
Implemented (ADR-0003, Accepted): 
 - Check catalog (services/check_catalog.py): 15 catalog checks with category, tool, base risk, prerequisites, expected evidence, keywords; automatic recommendation is a pure function of the analysis, so identical evidence gives an identical plan. Every outcome is explained: planned / skipped (not applicable) / deferred (prerequisite missing) / blocked (policy or target). Prompt mode = deterministic keyword selection (prompt stored as data, never interpreted); developer-defined mode = catalog check + validated parameters (no commands, risk or approval flags; extra fields are rejected); custom scripts need an accepted project script artifact and are always high risk with approval.
 - Policy (services/policy.py): effective policy = global + project, project only stricter, malformed values fall back to safest; approval floor high/critical (also a DB CHECK); intrusive and custom checks always need a human; who may decide is one pure function (Admin/Super Admin for high/critical and never the requester; Developers only for delegated low/medium with run access; production authorization Super Admin only + global flag + reason + 24 h cap). Policy admin routes (global: Super Admin; project: Admin with manage access) with value validation; llm_limits is not editable yet.
 - Plans API: create (rate limited), list, get, edit-while-draft, submit (re-checks target gate, recomputes approval need, freezes, stores SHA-256 content hash + policy snapshot; auto-approves when nothing needs a human), approvals inbox and decision (content hash re-verified; decisions final; requester can withdraw but never approve; refusals audited).
 - Target authorization (services/authorizations.py): request/list/revoke for remote dev/staging sources; hosts fixed by the source; path prefixes, methods, risk levels, window caps; gate_reason blocks tests whose remote target lacks an approved, unexpired, covering authorization (and production when the policy forbids it); decided via the approvals endpoint.
 - Audit actions added: plan.create/update/submit/auto_approved, approval.decision/denied/list_all, authorization.request/revoke/denied, policy.update/denied.
 - Frontend: services/api.js (credentials, CSRF header, error envelope, shape checks), sign-in form, project/plan list, plan review with loading/error/empty states, per-status groups with reasons, draft remove/submit, approve/reject/withdraw with reason, server refusal messages; Vite dev proxy for /api.
Database changes: ONE additive migration, 0003_plan_integrity (test_plans content_sha256/policy_snapshot/submitted_*, target_authorizations.justification, approvals self-approval CHECK and finality trigger, frozen-plan and planned-test guard triggers, test_runs plan guard). No data rewritten, no reset. Applied to the DISPOSABLE database only; the real sentinel-ai database was not touched. Existing tests that insert runs/planned tests directly were adjusted for the new guards (tests/integration/test_migrations.py).
Files: backend/migrations/versions/0003_plan_integrity.py; backend/src/sentinel_ai/{api/plans.py, api/governance.py, schemas/plans.py, services/{check_catalog,policy,plans,approvals,authorizations}.py, services/project_access.py (authorize_project), repositories/{plans,policies}.py, main.py}; pyproject.toml (E501 exemptions for catalog/service files with long user-facing strings); tests/unit/{test_check_catalog,test_policy}.py, tests/integration/test_plans_api.py (26 tests), tests/integration/test_migrations.py; frontend/src/{services/api.js, features/auth/SignIn.jsx, features/plans/*, app/App.jsx}, frontend/tests/{PlanReview.test.jsx, api.test.js, App.test.jsx}, frontend/vite.config.js; docs (API_DESIGN, DATABASE_SCHEMA, SECURITY_AND_SAFETY, OPEN_QUESTIONS, ADR-0003, backend/CLAUDE.md).
Commands actually run: temporary PostgreSQL 17 on a unix socket (own data dir, database sentinel_ai_test; recreated once after editing the unreleased migration); backend: pytest with and without TEST_DATABASE_URL, ruff check, ruff format --check, mypy, alembic upgrade 0002:0003 --sql (offline render only); frontend: npm run lint, npm test, npm run build.
Results (DISPOSABLE database only): pytest 234 passed (140 passed + 94 skipped without a database); ruff, format (71 files) and mypy (47 files) clean; frontend lint clean, vitest 11 passed, build ok.
Defects found and fixed by the tests: a URL path like "//evil.com" passed the URL-path pattern (could redirect a naive URL join) - now rejected; a failed submit rolled back the gate's blocked statuses, leaving a stale draft - now persisted before the error.
Acceptance criteria: (1) Users see what is planned before execution - met: plan API/UI show every check, risk, reason, prerequisites, evidence and approval need before anything can run; `execution_available:false` is stated. UI verified by unit tests only. (2) Approval rules enforced server-side - met: tests cover developer/peer/outsider/requester/Admin/Super Admin, delegation, project narrowing, production block, finality, hash binding, and DB-level constraints. (3) Unavailable or inapplicable checks explained - met (skipped/deferred/blocked each carry a reason; tested). (4) Plan snapshot linked to the resulting run - met at the schema level: test_runs.plan_id is NOT NULL and a trigger allows only an approved plan of the same project (tested by direct inserts); no API creates runs until Stage 7, so end-to-end linkage is NOT yet exercised.
NOT run: anything against the real sentinel-ai database (migration 0003 unapplied there); a live uvicorn/Vite session or browser; axe-core; any test execution (no runner exists, by design).
Known issues / owner actions: Q40-Q46; apply migration 0003 and commit; consider the Stage 7 worker re-validating gate_reason before execution.
Next action: owner review/commit. Stage 7 not started.
```

```text
Date: 2026-10-22
Stage: 6 (access and risk-approval review; no Stage 7 work)
Status: DONE pending owner review. Decisions Q47-Q51 need owner confirmation.
Review findings: (1) high/critical approval was effectively role-driven (any Admin/Super Admin with access) and Developer delegation was a global switch; (2) Super Admin had implicit access (audited) to every project, contradicting "privileges do not open every project's logs"; (3) project policy could be edited only by Admins, so the project owner did not control their risk levels; (4) risk levels were implicit.
Changes: services/project_access.py, api/deps.py, services/projects.py, services/approvals.py - no role has implicit project access (Super Admin branch, "privileged access" audit and "list all" removed). services/policy.py rewritten: eligibility = explicit grant + not requester + org role bound for high/critical + project designation or project managers; new policy keys allowed_risk_levels (org, project; intersection, malformed -> low only), high_risk_approver_roles (org; developers never), risk_approvers (project; designees validated as active project members, org-allowed role for high/critical); developer_approval_risk_levels removed. Project policy routes moved to /projects/{id}/policies[/{key}] and need manage access (any role). services/authorizations.py gate blocks risk levels the project disallows. check_catalog.RISK_DEFINITIONS (and exposed via GET /projects/{id}/policy); catalog risk values reviewed - no change needed, enforced by a unit test. PlanOut.viewer_can_approve (UI hint); the frontend uses it instead of guessing from the role. Docs: SECURITY_AND_SAFETY, API_DESIGN, ADR-0003 (amended), OPEN_QUESTIONS, backend/CLAUDE.md.
Database changes: NONE in this review (policy rows are existing public.policies; migration 0003 unchanged and still unapplied to the real DB).
Commands actually run: disposable PostgreSQL 17; pytest with and without it; ruff check; ruff format --check; mypy; frontend npm run lint/test/build.
Results (DISPOSABLE database only): pytest 239 passed (144 passed + 95 skipped without a DB); ruff, format and mypy clean; frontend lint clean, vitest 11 passed, build ok.
Tests added/changed: tests/unit/test_policy.py rewritten (eligibility matrix, designation, org bounds, validation, catalog risk rules); tests/integration/test_plans_api.py: roles add no access to plans/approvals, owner-chosen approvers and risk levels, project-manager policy control, production unlock path with grants, inbox scoping; test_projects_api/test_authorization updated for no implicit Super Admin access.
NOT run: real sentinel-ai database, live server/browser. No run/result/log routes exist yet; the isolation rule for them is documented and must be applied in Stage 7+.
```

```text
Date: 2026-10-23
Stage: 6 (owner decisions Q47-Q51; no Stage 7 work)
Status: DONE pending owner review.
Implemented: Q47 break-glass (migration 0004_break_glass, repositories/break_glass.py, services/break_glass.py, api/break_glass.py; project_access resolves READ for an active grant of a current Super Admin; every request served only by it is audited as breakglass.access; grant/revoke audited; grants listable by project managers; DB trigger forbids extension/edits, CHECK caps 4 h). Q48 approvals use resolve_explicit_access (break-glass or designation-without-membership never decides; production needs an explicit grant). Q49 high_risk_approver_roles may include developer only via the organization setting (Super Admin; projects cannot set it; empty value rejected); default unchanged. Q50 verified at every role/risk by tests (requester can only withdraw). Q51 already implemented; unused permissions approval.low_medium and policy.project_scope removed. get_snapshot now audits break-glass use.
Tests added: unit (developer opt-in, empty roles, malformed roles); integration: break-glass lifecycle (role gate, validation, read-only, other projects closed, audit rows, manager visibility, revoke by grantee/manager, strangers 404), expiry by DB clock and non-extension (DB trigger/CHECK), break-glass ends when the user is no longer a Super Admin, break-glass cannot decide or be designated, production approval needs explicit access, developer opt-in flow, no self-approval for developer/admin/super_admin at medium risk.
Database changes: migration 0004_break_glass (new table + guard trigger), additive. Applied to the DISPOSABLE database only. The real sentinel-ai database was not touched and awaits your approval for 0003 and 0004.
Commands actually run: disposable PostgreSQL 17 (recreated; the earlier scratchpad had been cleaned); pytest with and without it (repeated); ruff check; ruff format --check; mypy; frontend npm run lint/test/build.
Results (DISPOSABLE database only): pytest 246 passed (144 passed + 102 skipped without a DB); ruff, format (75 files) and mypy (50 files) clean; frontend lint clean, vitest 11 passed, build ok.
Observation: one full-suite run on the freshly created disposable cluster, before any change in this round, reported 1 failure that I could not reproduce (three later full runs passed 239/239, and all runs since pass). The failing test was not identified; treat as an unexplained flake until seen again.
NOT run: real database, live server/browser. Stage 7 not started.
```

```text
Date: 2026-10-23
Stage: 7 (job queue, batches, cancellation, recovery)
Status: DONE pending owner review (all acceptance criteria met with recorded evidence; execution is a stub until Stage 8).
Design: approved by the owner before coding (batch size 10, 2 batches/run, 4 global, lease 60 s, cancel grace 30 s, max attempts 1; migration 0005 approved; Q37 deferred). ADR-0004.
Implemented: migration 0005_job_queue (test_batches.heartbeat_at/lease_expires_at/not_before; test_batch_items); core/config.py JobSettings; execution/{interface,stub}.py (stub records every test as skipped, never passed/failed); repositories/runs.py; services/{job_state,runs,dispatcher,worker_runtime,reconciler}.py; schemas/runs.py; api/runs.py (create/list/get/cancel/batches/batch/results/events); jobs/{celery_app,tasks,worker}.py; Makefile worker/beat; celery[redis] dependency (kombu pinned <5.7 because 5.7.0rc1 was the only release allowing redis 8; redis is now 6.4.0).
Behavior: run created only from an approved plan whose content hash still matches, with the target gate re-run, per-project serialization and Idempotency-Key; batches claimed in PostgreSQL by the latest dispatch only (queue_task_id), so duplicate/stale/concurrent deliveries are no-ops; the worker re-checks the starter's access, plan approval and hash, project state and the target gate; cancel is DB-first (queued -> cancelled at once, claimed -> cancel_requested -> executor.terminate -> cancelled, or failed/cancel_unconfirmed); bounded retries only for failed_to_start/worker lost/internal error with exponential backoff and jitter; timeouts at worker and reconciler; reconciler (beat + on worker start, advisory-locked, idempotent) releases unclaimed dispatches, recovers expired leases, times out overruns/runs/queue waits, settles unconfirmed cancels, finalizes runs.
Tests added: tests/unit/test_job_settings.py (10); tests/integration/test_runs_jobs.py (30: batching, concurrency, idempotency, approval/hash/gate/policy refusals, duplicate and racing delivery, broker outage, queued and running cancel, batch isolation, unconfirmed cancel, retry bounds, timeouts, revalidation (user, access, project, authorization, policy), kill/lease recovery, late-worker takeover, scoping, break-glass read-only, no secrets in events); tests/integration/test_celery_broker.py (2, real broker); test_migrations.py updated for test_batch_items.
Commands actually run: private PostgreSQL 17 cluster and a throw-away Redis container for tests only; pytest (three configurations above, repeated); ruff check; ruff format; mypy; alembic heads; celery worker and beat smoke runs with SENTINEL_ENV_FILE=/dev/null; poetry add celery[redis] and kombu pin.
Results: see section 2.
Observation: one full-suite run reported 1 failure in tests/integration/test_projects_api.py::test_analysis_result_separates_facts_inferences_and_gaps_and_is_persisted (it passes alone and in 6 later runs; same intermittent pattern noted in the 2026-10-23 Stage 6 entry). Not caused by or related to Stage 7 code; not root-caused (Q57).
NOT run: real database, your dev Redis, a live API server, browser, frontend checks (no frontend change), load/soak tests, any sandboxed execution (Stage 8). Hard-kill recovery was tested against a real Celery process, but not with a long-running real sandbox.
Acceptance criteria: queued jobs cancellable (tested); running jobs request termination through the executor interface and report the outcome (tested with the stub/Probe executors; a real sandbox arrives in Stage 8); completed batches survive later cancellation (tested); duplicate delivery does not duplicate work (tested, incl. concurrent threads); stuck jobs reconciled and visible via job_events (tested); worker restart behavior tested (simulated kill + real SIGKILL) and documented (JOB_AND_SANDBOX_DESIGN, ADR-0004).
Known issues: Q52-Q57 in OPEN_QUESTIONS.md.
Next action: owner review and commit; apply migrations 0003-0005 to the real database; Stage 8 on approval.
```

```text
Date: 2026-10-23
Stage: 8 (sandboxed execution foundation)
Status: DONE pending owner review (all acceptance criteria met with recorded evidence; no project code is executed yet, by design).
Design: threat model and plan approved by the owner before coding; five decisions approved (hardened Docker baseline, sandbox_smoke check, network always off, stdout/stderr/manifest evidence, Docker integration tests). ADR-0005, docs/architecture/SANDBOX_THREAT_MODEL.md.
Implemented: sandbox/{Dockerfile,entry.py,smoke.py} (trusted in-image runner: bounded stdin archive, strict extraction, own timeout; image built locally from python:3.12-slim with no pull); execution/{sandbox_spec,docker_runner,docker_executor,commands,evidence,factory}.py; interface additions (WorkspaceRef, EvidenceItem, `blocked` outcome); worker resolves a project-scoped, hash-recorded workspace, stores evidence artifacts (artifact_store.put_bytes, repositories insert_evidence_artifact) and re-checks lease ownership after each execution; reconciler takes cleanup/sweep hooks (lost, overrunning and unconfirmed-cancel batches; janitor); catalog check sandbox_smoke (low risk, developer-selectable, `automatic=False`, excluded from automatic and prompt plans); settings JOB_EXECUTOR=docker and SANDBOX_* (image, runtime, scope, cpus 1, memory 512 MiB, pids 128, workspace 128 MiB, tmp 16 MiB, extract 96 MiB, file 32 MiB, timeout 300 s, output cap 1 MiB); `make sandbox-image`.
Behavior: --network none always; read-only rootfs; cap-drop ALL; no-new-privileges; user 65534; no mounts/devices/socket/env; ZIP over stdin; fixed command table; status from docker inspect; evidence redacted/capped/hashed; cleanup by label and scope on success, failure, timeout, cancel, OOM, worker loss.
Tests: see section 2. Docker tests prove, in real containers: no host secrets in the environment, every network route blocked (host loopback, bridge gateway, internet, metadata, DNS), no Docker socket or host paths, read-only rootfs and noexec tmpfs, uid 65534 with zero capabilities, seccomp and no-new-privileges, memory/pids/tmpfs-size/file-size/output limits, timeout, frozen-runner host deadline, cancel, removal after every outcome, orphan cleanup by batch, scope-limited janitor, six hostile archive kinds rejected, and project code never executed.
Commands actually run: docker build (local base, no pull); docker create/start/inspect/rm for the tests; private PostgreSQL 17 cluster and a throw-away Redis container for tests only; pytest in five configurations (section 2); ruff check/format; mypy; alembic heads; real Celery worker process smoke runs.
Observations: three first-run test failures were wrong assumptions in my tests (OOM exit code 247 not 137; killing the in-container runner ends the container; a "large" ZIP compressed below the limit), fixed in the tests. One product fix came from review: a worker whose batch the reconciler already took no longer records a late result.
NOT run: the real database, your dev Redis, a live API server, a browser, frontend checks (no frontend change), gVisor/Kata runtimes (none installed; SANDBOX_RUNTIME is validated and passed through but untested), rootless Docker, load/soak tests, any real project code (Stage 9).
Acceptance criteria: a sample command runs only inside the sandbox (tests + end to end; the host never executes it); the sandbox cannot read backend secrets or unrelated workspaces (env, mounts, per-container tmpfs, project-scoped source lookup, hash check); CPU/memory/process/time/filesystem/network limits are enforced as configured (asserted from the daemon's HostConfig and by behavior); containers and workspaces are cleaned after success, failure, timeout, cancellation, OOM and worker loss; risky or unauthorized targets are blocked before execution (network checks and unverified or foreign archives are `blocked`, unknown checks `skipped`, Stage 7 revalidation unchanged).
Known issues: Q58-Q64 in OPEN_QUESTIONS.md.
Next action: owner review and commit; build the image; apply migrations 0003-0005 to the real database; Stage 9 on approval.
```

```text
Date: 2026-10-24
Stage: 9 (first QA execution path)
Status: DONE pending owner review (all acceptance criteria met with recorded evidence; Playwright not started; UI verified by unit tests only).
Design: the owner asked to proceed straight to implementation; decisions were taken within that approval and recorded in ADR-0006 for review (Q65): offline vendored pytest (Q60), URL targets stay blocked (Q26), noexec kept (Q62), project code gated behind explicit opt-in flags (Q59), exit-code-derived status, evidence download rules (Q64).
Implemented: migration 0006 (test_results.status += not_run; test_case_results); sandbox/vendor.py + Dockerfile (pytest, pluggy, iniconfig, packaging, pygments vendored from poetry.lock, no network, no compiled extensions); sandbox/entry.py result-file framing (regular file, O_NOFOLLOW, 2 MiB cap, nonce, sha256); execution/{junit,frames}.py (defensive parsing, last valid frame, frame scrubbing); commands.py pytest_unit with validated target_path/timeout_seconds; docker_executor (project-code gate, parameters, result handling, exit-code mapping, redacted cases and evidence incl. junit.xml, manifest v2); docker_runner stdout tail buffer; settings SANDBOX_ALLOW_PROJECT_CODE / SANDBOX_ACCEPT_SHARED_KERNEL with validator; worker passes parameters, stores cases, continues after a single test timeout, writes explicit not_run results (also for batches cancelled or timed out while queued); API GET /test-runs/{run}/results/{result} and GET /artifacts/{id}/content (project grant, run evidence only, hash re-check, audit, attachment headers), progress cases_by_status; frontend RunsPanel (start with idempotency key, history, cancel, polled progress, results with distinct honest labels, cases, plain-text evidence view) wired into the plans page.
Bugs found by the new tests and fixed: JUnit time="1e999" crashed the parser (OverflowError); one control byte made the whole report unparseable (now stripped); a single test timeout wrongly ended its batch; the run detail view kept polling after the run finished (stale status).
Tests added: see section 2. Docker/pytest tests prove, from inside real pytest runs: no env secrets, no network (host loopback, gateway, internet), no Docker socket, read-only root and vendored code, uid 65534, zero capabilities, non-executable tmpfs; plus forged results, XML bomb/DOCTYPE, oversized/symlink/FIFO/garbage result files, output flood with the result still found, infinite loop (timed_out), memory hog (error/OOM), fork bomb (contained), cancel, project-code gate off (blocked, no container), hostile archive (blocked on the host).
Commands actually run: make sandbox-image (vendor + docker build, local base); pytest in five configurations; ruff check/format; mypy; alembic heads; npm run lint/test/build; private PostgreSQL 17 and a throw-away Redis container for tests only; real Celery worker process runs.
NOT run: the real database, your dev Redis, a live API server, a browser (no axe/accessibility run), Playwright/browser tests (not started, Q69), gVisor/Kata, rootless Docker, any JavaScript or non-Python runner, load/soak tests, a dependency-installing flow (none exists, Q66).
Acceptance criteria: a user can select an approved plan, start a run, watch progress, cancel it and inspect evidence (API tested end to end; UI tested with Vitest/jsdom only); result states distinguish passed, failed, skipped, blocked, timed_out and not_run (plus error, cancelled, failed_to_start), all asserted in API tests and shown with distinct labels; failed_to_start is never reported as a test failure or pass (missing-image run: result failed_to_start, no cases, batch failed_to_start); run ownership and artifact authorization are enforced (outsider/anonymous/other-run/uploads/tampered/missing/traversal checks, admin and super admin need a grant, break-glass read-only and audited, read members can read but not start/cancel).
Known issues: Q65-Q72 in OPEN_QUESTIONS.md. Most real projects will report error until a dependency path exists (Q66).
Next action: owner review and commit; rebuild the image (make sandbox-image); apply migrations 0003-0006 to the real database; Stage 10 on approval.
```

### Stage 10 - Security integrations and finding verification (2026-10-24)
Date: 2026-10-24
Owner go-ahead: "go with stage 10 ... do not start stage 11"; owner approved adding Bandit via `poetry add --group dev bandit` (network to PyPI; `poetry.lock` updated; no other network use).
Built: `bandit_static` fixed sandbox command (`python -P -m bandit`, vendored offline, not a project-code check); `execution/bandit_report.py` (defensive parse, no code snippets, secret-quoting messages redacted, stable fingerprints); `ScanOutcome`/`FindingResult` in the executor interface; Bandit status mapping (valid report required for `passed`); migration `0007_findings`; `repositories/findings.py`, `services/findings.py` (ingest, de-duplication, reopen, re-scan verification, review states, human verification), `api/findings.py` + `schemas/findings.py` (list, detail, status, verification); worker hook `_store_findings`; `sandbox/vendor.py` (Bandit stack, PyYAML C accelerator skipped, dist-info entry points kept); frontend `features/findings/` + API client; ADR-0007; threat model T17-T21; docs and Q73-Q80.
Acceptance: every finding links to its stored scan report (tested); scanner output is `unverified`, never confirmed (tested; `confirmed` needs a person, a note and evidence, also refused by the DB); unauthorized targets and intrusive profiles stay blocked because Semgrep/dependency audit/ZAP/load have no runner and the planning gates are unchanged (tested: no runner, approval flags); findings show severity, tool confidence, verification state and limitations (API and UI tested).
Bugs found by tests and fixed: a scan was attached to timed-out/cancelled/OOM outcomes (now only for a scan that ran to its own end); my first policy let developers mark `false_positive` (the documented matrix says Admin+; corrected and tested).
NOT run: the real database, dev Redis, a live API server, a browser (no axe), Semgrep, dependency audit, OWASP ZAP (none built), any non-Python scanner, gVisor/Kata, load tests.
Known issues: Q73-Q80. Next action: owner review and commit; rebuild the image (`make -C backend sandbox-image`); apply migrations 0003-0007 to the real database after review; Stage 11 on approval.

### Stage 10 (completion) - Semgrep, offline dependency audit, ZAP, de-duplication (2026-10-23)
Date: 2026-10-23
Owner request: finish Stage 10 (Semgrep offline, dependency audit with an offline advisory strategy, ZAP via Docker with strict gating, cross-scanner dedup, normalization, tests, docs). No accessibility work.
Environment: **no outbound network** (probing was denied), no Semgrep, ZAP image, pip-audit or advisory data. Decisions in ADR-0008; Q73-Q75, Q79 updated, Q81-Q86 opened.
Built: `semgrep_static`, `dependency_audit`, `zap_baseline`, `zap_active` fixed commands (per-kind image); `execution/{report_common,scan_report,semgrep_report,dependency_report,zap_report}.py` (Bandit now shares `report_common`); `sandbox/dep_audit.py` + `sandbox/advisories.py` (offline audit, operator-run OSV bundle builder, image-label age check); `sandbox/semgrep-rules/` (16 local rules), `Dockerfile.semgrep`, `Dockerfile.zap`; `SandboxSpec.egress`/`EgressSpec` (validated network, pinned host, black-hole DNS) and ZAP gates in `DockerSandboxExecutor._prepare_zap`; worker passes an authorized `TargetRef`; settings `SANDBOX_SCANNER_IMAGE`, `SANDBOX_ZAP_*`, `DEPENDENCY_ADVISORY_MAX_AGE_DAYS`; migration 0008 (`cwe`, `component`, `aliases`, `group_id`, `finding_groups`); `services/dedup.py`; `GET /projects/{id}/finding-groups`; `related` on finding detail; findings panel shows tool, linked duplicates; Makefile targets; threat model T22-T31 + ZAP checklists; catalog `dependency_audit` no longer needs egress (risk low).
Commands run: ruff check/format --check (128 files clean); mypy (84 files clean); `pytest` with a disposable PostgreSQL 16 container (127.0.0.1:55439, local image, removed afterwards) and local Docker: **592 passed, 4 skipped** (real-broker Redis tests; no Redis configured); frontend `npm test` 35 passed, `npm run lint` clean; Stage 10 additions: 100+ unit tests (`test_security_scanners.py`), 7 DB tests (`test_scanner_findings.py`), 1 Docker test (`test_scanner_docker.py`, builds a throw-away image with SYNTHETIC advisories), migration test updated.
Verified in a real container: dependency audit end to end (lockfile parse, OSV range matching, framing, host parsing, label-based age check; `--network none`, read-only root, caps dropped). Observed: Semgrep with no scanner image ends `failed_to_start`, never a pass; ZAP unconfigured ends `blocked`.
NOT run / NOT verified: **Semgrep** (not installed; flags, report shape, image build and bundled rules unvalidated); **OWASP ZAP** (no image; Dockerfile, script paths, report location, JVM under noexec tmpfs, and the host-firewall restriction unvalidated; no target was ever contacted); `make advisories` against OSV (never run; no real advisory data used; compaction unit-tested); real database; dev Redis; browser/axe; gVisor/Kata.
Tests changed because behaviour legitimately changed: `test_sandbox.py` (command set), `test_bandit_scanner.py` (semgrep/deps/zap now have runners), `test_sandbox_e2e.py`/`test_pytest_e2e.py` (runner-less check is now `js_unit`/`openapi_lint`). One full-suite run showed a failure in `test_projects_api.py::test_analysis_result_...`; it passed in isolation and in the final full run (not root-caused; possibly timing).
Known issues: Q73-Q75 (verification), Q81-Q86. Next action: owner review and commit; `make advisories`, `make sandbox-image`, `make scanner-image`; apply migrations 0003-0008 after review; verify Semgrep and ZAP per ADR-0008 before relying on them.

### Stage 10 follow-up - real-tool verification (2026-10-23)
Date: 2026-10-23
Run (owner checklist): `make advisories` (OSV PyPI 31,031 / npm 232,804 advisories); `make sandbox-image`; real audit in the locked-down container (Django 2.2.0, lodash 4.17.20 matched real CVEs, current versions unmatched); `make scanner-image SEMGREP_VERSION=1.182.1 DOCKER_BUILD_ARGS=--network=host` (new Makefile variable, build step only); Semgrep ran offline through the executor path, 16/16 bundled rules fired correctly (`semgrep --validate` needs the network and was not usable); pulled `ghcr.io/zaproxy/zaproxy:stable` (ZAP 2.17.0), built `sentinel-zap-runner:stage10`, ran the baseline in a lab (`--internal` network, local target, same `create_argv` hardening): found and fixed three Dockerfile defects, then exit 0 / 44 s / report framed and parsed (15 alerts); migrations 0003-0008 SQL reviewed (additive only), real database was at 0007, `alembic upgrade head` applied 0008 (now head); tests: full run 591 passed + 1 failed (the sandbox env allowlist test, because `entry.py` now sets two constant SEMGREP_* variables; allowlist extended for exactly those two and their values asserted; that file then passed, 30/30); ruff/format/mypy clean.
NOT done: host-firewall restriction for ZAP (needs root), ZAP against a public/authorized remote target, `zap_active`, OSV licence review (Q82), scheduled advisory refresh. ZAP remains disabled (`SANDBOX_ZAP_*` unset, attestation false).
Next action: owner review; provision and test the firewalled ZAP network, then enable ZAP per the threat-model checklist; Stage 11 on approval.

### Frontend F0 - foundation (2026-10-23)
Date: 2026-10-23
Owner go-ahead: approved the F0-F9 plan with decisions (react-router-dom; axe-core with a Vitest integration; system fonts; informational Request Access page; overview composed from existing endpoints; use the owner's report screenshot; follow F0-F9 order) and said "start with F0 only ... do not start F1 until I approve F0". Stage 11 untouched.
Built: design tokens and Light/Dark/System themes (persisted, no flash); responsive top navbar shell (no sidebar) with skip link, Escape-closes-menu, focus to `<main>` on navigation; auth context (session logic moved out of `App`); router in `main.jsx`; shared components (Button, StatusBadge, PlannedBadge, Card, Metric, ProgressBar, Field, DataTable, Pagination, Dialog/ConfirmDialog, Toast, TabNav, PageHeader, EvidenceViewer, loading/empty/error/permission states, ThemeToggle, Icon); status vocabulary (`lib/status.js`) and error mapping (`lib/errors.js`); `useLoad`, `usePagination`, `useDocumentTitle` hooks; developer-only `/design-system` gallery (not in the production build); informational NotFound page. `PlansPage` now uses the shared `useLoad`; `plans.css`/`runs.css` hard-coded colours replaced by tokens; the Vite template `index.css` removed. API client unchanged; no backend change.
Dependencies: `npm install --save-dev axe-core vitest-axe` (network to npm, owner-approved; 0 vulnerabilities reported). `react-router-dom` ^7.18.4 was already in `package.json` and `node_modules` when F0 started (not installed by this session).
Commands actually run (frontend/): `npm run lint` (oxlint: clean, no warnings); `npx vitest run`: **12 files, 127 tests passed** (was 5 files, 35: the 35 existing tests still pass; `App.test.jsx` only gained a `MemoryRouter` wrapper because `App` no longer creates its router); `npm run build`: ok, 58 modules, JS 300 kB (94 kB gzip), CSS 17 kB; confirmed `design-system` is absent from the production bundle. Sanity checks: axe is shown to flag an unlabeled input and an image without alt; the contrast test parses 24 colour tokens per theme.
Tests added: theme logic (storage failure, system resolution, apply); token contrast from the real `tokens.css` (WCAG 4.5:1 text and 3:1 non-text, both themes); status vocabulary (every value has tone and icon, result states distinct, finished/approved/unverified never success, unknown neutral); error mapping (no 5xx echo); components (disabled reason, field associations, dialog focus trap/Escape/restore, required-reason confirm, toast roles and auto-dismiss, state components, table/pagination, evidence as plain text with truncation, tab/breadcrumb current page); shell (skip link, landmarks, no sidebar, auth-aware navbar, menu toggle, theme switching and persistence, system follows OS changes, not-found and focus-to-main); axe on the signed-out page, not-found page and component gallery in light and dark.
Acceptance (F0): themes persist and apply before paint (logic tested; first-paint script present, not observed in a browser); responsive navbar without sidebar (markup and behaviour tested; layout not viewed); shared components handle loading/error/empty/permission states (tested); status never by colour alone (icon + text, tested); existing panels still work (existing 35 tests pass; the workspace route renders them, tested); lint, tests and build pass.
NOT run / NOT verified: any real browser (no visual check of layout, the mobile menu, dark mode, the pre-paint script or the gallery), screen readers, manual keyboard pass, colour contrast of rendered pixels (token pairs only), the dev server against a live backend, responsive widths. Automated axe cannot prove accessibility (Q89, Q90).
Known issues: Q87 (report screenshot not found; needed before F5), Q88 (CSP and the inline theme script), Q89, Q90. `FindingsPanel`/`RunsPanel` still use their own loaders and unstyled-by-component markup; they are restyled by base.css only until F5/F6.
Changed files: frontend/{index.html, package.json, package-lock.json, vite.config.js, src/main.jsx, src/app/**, src/components/**, src/features/design/**, src/features/plans/{PlansPage.jsx,plans.css}, src/features/runs/runs.css, src/hooks/**, src/lib/**, src/styles/**, src/theme/**, src/index.css (deleted), tests/**}; docs/{IMPLEMENTATION_PLAN.md, PROJECT_TRACKER.md, OPEN_QUESTIONS.md, decisions/ADR-0009-frontend-foundation.md}, frontend/{CLAUDE.md, README.md}.
Next action: owner review of F0 (run `npm run dev`; try Light/Dark/System and a narrow window; open `/design-system`). F1 not started.

### Frontend F0 - structure alignment (2026-10-23)
Owner requirement: component- and page-based architecture; each component's CSS beside its JSX; only global styles in `styles/`; clear separation of components, pages, hooks and API services; apply to F0-F9 and files already created; report conflicts; add the rule to the frontend instructions.
Conflicts found in F0 and fixed (moves and CSS splits only, no behaviour change): (1) `components/ui.css` (one stylesheet for 14 components) split into one CSS file per component, imported by its JSX (`Button.css`, `StatusBadge.css`, `Card.css`, `Field.css`, `states.css`, `DataTable.css`, `Pagination.css`, `TabNav.css`, `PageHeader.css`, `Dialog.css`, `Toast.css`, `EvidenceViewer.css`, `ThemeToggle.css`, `Icon.css`); (2) `app/shell.css` split into `Navbar.css`, `AppShell.css` and `pages/DesignSystemPage.css`, with the three utilities used across features (`.muted`, `.error`, `.stack`) moved to `base.css`; `.skip-link` moved from `base.css` to `AppShell.css`; `main.jsx` now imports only the two global files; (3) route pages moved out of `app/` and `features/design/` into a new `src/pages/` (`WorkspacePage`, `NotFound`, `DesignSystemPage`); (4) hooks moved into `src/hooks/` (`useAuth`, `useToast`, `useTheme`, previously in `app/`, `components/`, `theme/`).
Left as is, recorded as known deviations in `frontend/CLAUDE.md` (pre-existing, fixed in their own phases): `plans.css`/`runs.css` shared by several panels; `PlansPage` still in `features/plans/` (becomes a page in F4); `FindingsPanel`/`RunsPanel` own loaders.
Commands run (frontend/): `npm run lint` clean; `npx vitest run` three times: 127 passed each time; `npm run build` ok. Production CSS fell from 16.8 kB to 12.3 kB: expected, because the CSS of components no page uses yet (Card, DataTable, Dialog, Pagination, TabNav) is no longer bundled; verified the CSS of the components that are used is present. One earlier run (right after an aborted script left the tree almost unchanged, only a stray `Icon.css`) showed 1 failing test out of 127; its name was not captured, and 11 later full runs all passed, so it is an unexplained intermittent failure, not reproduced.
NOT run: browser checks (unchanged from F0).
Docs: `frontend/CLAUDE.md` (new "Architecture and file organization" section), `frontend/README.md`, ADR-0009 decision 10.

### Frontend F1-F4 (2026-10-23)
Date: 2026-10-23
Owner go-ahead: "start F1 and complete F2, F3, F4 and F5; keep frontend testing efficient; run lint, the full suite and the build after F1-F4; give a short manual checklist; do not go to the next phase until I say". Stage 11 untouched. F5 was **not** built: the report screenshot the owner asked to be used as the layout reference is not on this machine (Q87) and the owner's earlier instruction was to ask before building that phase.
Built (F1 public site): `/` home (hero with a decorative QA-pipeline illustration, how it works, capability grid with Available now / Partly available / Planned badges worded from this tracker, accessibility statement that makes no conformance claim); `/signin`; `/request-access` (informational: no form, says it sends nothing, role guide, what to ask the administrator).
Built (F2 auth/account): sign-in form (labels, autocomplete, show/hide password, field validation, one vague wrong-credentials message, rate-limit message); `RequireAuth` route guard with `?next=` (accepted only as an in-app path); session expiry (a 401 on a protected call returns the user to sign-in with a "session ended" notice); `/account` (profile, change password with confirm field, active sessions with revoke); navbar now Home / Projects / Approvals (signed in) or Request access (guest) and the user name links to the account page.
Built (F3 projects): `/projects` list with create dialog and archived toggle; project frame with section tabs (Overview, Setup, Analysis, Plans, Runs, Findings); Overview composed from the existing list endpoints (latest analysis, plans, latest run with progress and result counts, findings counts, pending approvals), each panel loading independently; Setup (sources: list, ZIP upload sent as the raw body, Git/localhost/remote descriptors with "not contacted" wording, remove; members: list, change access, remove, add via user search; archive with confirmation); Analysis (run on a ZIP source, history, report showing facts, inferences with confidence, and gaps).
Built (F4 plans/approvals): Plans list and "Generate recommended plan"; plan page reusing the existing `PlanReview` (edit, submit, approve/reject); `/approvals` with status filter, plan rows linking to the plan page and target-authorization requests decided in a dialog that shows the target, requires the 10-character reason for high/critical approval, and shows the server's refusal. Runs and Findings tabs keep the existing panels unchanged in behaviour, labelled as the existing view.
API client additions (no backend change): create/get/archive project, members, user search, sources (ZIP raw upload, URL descriptors, remove), analyses, authorizations, change password, sessions, `setUnauthorizedHandler`. Removed: `WorkspacePage`, `PlansPage`, old `SignIn.jsx` (replaced).
Commands actually run (frontend/): `npm run lint` clean (no warnings); `npx vitest run`: **14 files, 152 tests passed** (was 127; test files replaced where the old workspace page was removed: shell, a11y, auth, approvals, projects, api additions); `npm run build` ok (134 modules; JS 360 kB / 110 kB gzip; CSS 22.7 kB); `design-system` absent from the production bundle. Every CSS file other than the two global ones and the two known deviations sits beside a same-name JSX file (checked by script).
Tests added (critical paths only): safe `next` redirect handling (open-redirect cases); sign-in, wrong credentials, empty-field validation, sign-out; route protection with return to the requested page; session expiry end to end with the real API client over a stubbed network; approvals (list, plan link, informed decision dialog, 10-character reason rule, reject without reason, server refusal shown); project creation (validation, server error, open created project); overview from real calls and honest empty panels; permission refusal shown in place; ZIP upload request shape and CSRF; project-shape validation; 401 expiry handler (not fired for sign-in or the session probe); password change request shape; axe on home, sign-in, request access and the gallery in light and dark. No tests were written for simple presentational components.
NOT run / NOT verified: any real browser (no visual check of any new page, the mobile menu, dark mode, the hero illustration); a live backend (all page tests use a fake API or a stubbed network; nothing was tried against the real server: ZIP upload, analysis, member changes, approval decisions and password change are untested end to end); screen readers and a manual keyboard pass; rendered colour contrast.
Known issues: Q91 (a developer cannot add a member: user search is admin-only), Q92, Q93, Q87 (F5 blocked). The members add dialog, the approvals project names (extra project-list call) and the overview (several calls) depend on the backend as it is.
Manual browser checklist for the owner (about 10 minutes, `npm run dev` with the backend running and a user account):
1. Home `/`: headline, hero illustration, "Available now / Partly available / Planned" badges read correctly and match what is really built. Toggle Light, Dark, System; reload and confirm the choice sticks with no flash.
2. Narrow the window to phone width: menu button appears, opens and closes (Escape too), nothing overflows sideways on home, projects or a table.
3. Visit `/projects` signed out: you land on sign-in; after signing in you return to `/projects`. A wrong password shows one message; Tab/Enter work through the form; show/hide password works.
4. Account page: change password (wrong current password is refused; mismatch is caught); sessions list shows "this session" without a sign-out button.
5. Projects: create one (empty fields are caught), open it, check each tab; Overview panels say "none yet" rather than showing numbers when empty.
6. Setup: upload a small ZIP and register a Git URL; the URL one says it was not contacted; remove a source (confirmation appears).
7. Analysis: run it on the ZIP; the report shows facts, inferences and gaps and says no code was run.
8. Plans: generate a plan, open it, submit it; Approvals: confirm a pending request appears for a user who may decide it, approve one (reason rule) and reject one.
9. Runs and Findings tabs: still behave as before (marked as the existing view).
10. Keyboard only: you can reach every control, focus is always visible, and a dialog traps Tab and closes with Escape.
Next action: owner review of F1-F4. F5 needs the report screenshot (give the path, or say to proceed from ui-ux-design.md). F6 not started.

### Frontend F1 - owner style feedback (2026-10-23)
Owner feedback after viewing F1-F4: theme control should be a compact icon pill (System, Dark, Light); the pages left too much empty space at wide screens; the hero should be centred and minimal in the manner of crezco.com (used only as layout inspiration: centred headline, short copy, two actions, full-width circuit illustration; nothing copied). Owner repeated: do not start F6.
Changed: `ThemeToggle` is now three icon-only buttons (visually hidden names kept, `aria-pressed` plus a ring for the active one); content width 72rem to 90rem and gutters up to 4rem (`tokens.css`); navbar is brand left, links centred, actions right; the home page is full-bleed (`AppShell` skips the container for `/`; `.container` is now a global utility in `base.css`); new centred `Hero` with an eyebrow pill, large headline, pill-shaped buttons and a wide decorative circuit illustration (`PipelineVisual`, hidden from assistive technology); workflow and capability sections use more of the width (capability cards 22rem minimum); closing call-to-action centred.
Commands run (frontend/): `npm run lint` clean; `npx vitest run` 14 files, 152 passed (no test changes needed); `npm run build` ok.
NOT run / NOT verified: any visual check in a browser (hero proportions, the illustration cropping at phone width, the wider layout, the icon pill in dark mode were not seen by Claude).

### Frontend F1 - animated hero scene and technical grid style (2026-10-23)
Date: 2026-10-23
Owner request: a custom animated hero visual inspired by the reference screencast (circuit-style line animation; SVG, CSS and React only; connected paths, moving directional arrows, subtle geometry, a central testing-system visual; monochrome with restrained status colours; responsive, performant, reduced-motion safe), plus a technical style taken from a sample (low-opacity line grid behind the hero, mono utility ribbon and labels, bordered step grid, no cyan colouring), and a page that uses the full screen width. Owner again: do not start F6. How the reference was read: frames were extracted from the screencast (it shows the crezco.com hero: traces with rounded bends, small arrows travelling both ways, a hexagon with rotating arcs, squares, rings, crosses, dashed lines, brackets); the Sentinel scene is an original drawing, nothing is copied.
Built: `features/home/HeroVisual` (+ CSS): six connected circuit traces (inputs in from the left, evidence out to the right, one return), ten arrows travelling along them (SVG `animateMotion`), a hexagonal testing system (three turning rings, a checklist panel with a sweeping scanner), status nodes (pass, fail, skip) along the traces, a segmented progress chip, crosses, dots, brackets and corner ticks. It holds no product data or numbers. Accessibility and performance: hidden from assistive technology (the "How it works" text carries the meaning); no motion for `prefers-reduced-motion` (arrows rest in place); a visible Pause/Play button (WCAG 2.2.2); animation also pauses while the scene is off screen or the tab is hidden (`hooks/usePauseOffscreen`); only transform/opacity/dash-offset animations; `hooks/useReducedMotion`. Hero restyled: faint line grid (new `--grid-line` token, both themes), mono utility ribbon, mono section tag, light-over-bold headline. The ribbon carries descriptive labels only; the sample's fake "SYSTEM: STABLE", coordinates and run id were deliberately not used (they would be made-up status). Workflow steps and capability cards now share one bordered-grid style (mono numbers, uppercase mono step titles, hover lift, rows fill on wide screens). Page width: `--content-width` 120rem, so content spans the screen up to 1920px with gutters, and the hero scene is edge to edge.
Bug found and fixed: the split headline had no space between its spans, giving the accessible name "you cantrace" (caught by the axe test).
Test fixed: `RunsPanel.test.jsx` "follows progress while a run is active" raced its own 20 ms poll and failed under load (likely the earlier unexplained intermittent failure); poll slowed to 150 ms and the final wait to 500 ms. New test: `hero.test.jsx` (arrows move by default, pause and play work, no animation under reduced motion).
Commands run (frontend/): `npm run lint` clean; `npx vitest run`: 15 files, 154 tests passed (twice); `npm run build` ok (JS 366 kB / 112 kB gzip, CSS about 28 kB). Visual check by Claude this time, using headless Chrome screenshots of the production build: desktop 1850 px (light and dark, the dark one by seeding the saved theme) and a 390 px phone width; layout, grid, hero scene, step grid, capability grid and the dark theme looked correct.
NOT verified: motion itself (screenshots are still frames, so arrow travel, ring rotation and the scanner were not seen moving); other browsers (SMIL `animateMotion` is supported in current Chrome, Firefox and Safari, but only Chrome was used); a real screen reader and keyboard pass; pages other than home were not re-screenshotted after the wider layout.

### Frontend F6-F9 (2026-10-23)
Date: 2026-10-23
Owner go-ahead: "complete F6 to F9, follow the rules, essential testing only". F5 was not part of this request and is still blocked on the report screenshot (Q87/Q97). Stage 11 untouched; no backend change.
Built (F6 findings): project Findings tab is now a page: honest "leads, not verdicts" notice; filters (status and severity through the API, tool on the loaded list); summary figures; table with severity, tool confidence, verification state and status as separate columns; pagination; linked-duplicate groups (`GET finding-groups`, linked never merged); finding page `/projects/:id/findings/:findingId` with summary, limitations, related findings, evidence (loaded on request, plain text), verification attempts, review controls (only real transitions, reason for risk decisions, note of 10+ characters for a judgement, server refusal shown) and history. The old `FindingsPanel` was replaced; the dead findings rules were removed from `runs.css`.
Built (F7 governance/admin): project Governance tab: target authorizations (list, request dialog with scope, methods labelled when they change data, risk levels, window and justification, revoke with confirmation), effective approval policy with risk-level definitions and editors for the two settings a project may tighten, break-glass records with a grant form shown only to super admins. `/admin` (admins and super admins; others see an explanation and no nav link): users (search, create, edit role/name/active) and organization policy editors (risk levels, approver roles, production-testing flag). New `RequireRole`, `PolicyEditor`, `SectionHeader`; the navbar filters by role.
Built (F8): `/roadmap` (public): planned work for Stages 11-16, Stage 11 marked paused, plus the limits of what exists today; read-only, no controls inside the list. The planned items in the home capability grid and this page use the same wording rules.
F9 hardening: axe checks on seven data-rich signed-in pages (projects, setup, finding detail, governance, approvals, account, admin). They found a real defect: the table scroll region and its enclosing card had the same name (duplicate landmarks, e.g. "Target authorizations"); fixed in `DataTable` (region is now named "<caption> table"). Docs updated.
Commands run (frontend/): `npm run lint` clean; `npx vitest run`: 17 files, 167 tests passed; `npm run build` ok (JS 394 kB / 120 kB gzip). Tests kept to critical paths: findings (unverified display, filters through the API, no "clean" claim on empty, evidence as plain text, transitions and reason rules, refusal shown), governance (authorization request body and validation, revoke needs confirmation, policy save and refusal, break-glass only for super admin), admin (role-gated page and link, create user validation and refusal), roadmap (planned stage labels, no controls), plus the axe pass.
NOT run / NOT verified: any browser view of the new pages (an attempt to run a throwaway mock backend for screenshots was declined, so the new signed-in pages were not looked at on desktop or phone); all of F6-F9 against the real backend (every test uses a fake API); screen reader and manual keyboard pass; the earlier home-page screenshots remain the only visual checks.
Known issues: Q94-Q97.
Manual browser checklist for the owner (about 15 minutes, backend running, a super admin account):
1. Findings tab: filters change the list; open a finding; evidence "View" shows plain text; try a status change and a judgement (note under 10 characters is refused in the form); duplicates section lists linked findings.
2. Governance tab: request an authorization for a URL source (short reason is refused), see it appear as pending; approve it from Approvals; revoke it; change a policy list and save (a refusal from the server is shown).
3. Admin (as admin): the Admin link shows; as a developer it does not and `/admin` explains why. Create and edit a user; try creating a super admin as a plain admin and read the refusal.
4. Roadmap: every item says Planned with its stage; nothing clickable inside the cards.
5. Phone width (about 390 px) on Projects, Findings, Governance and Admin: no sideways page scroll (tables scroll inside their box), dialogs fit, buttons are reachable.
6. Light, Dark and System on each of the above; keyboard only through a dialog (Tab stays inside, Escape closes).
Next action: owner review. F5 needs the report screenshot. No further frontend phase is planned after F9.

### Frontend F5 - runs and results report (2026-10-23)
Date: 2026-10-23
Owner request: build F5 from `docs/architecture/ui-ux-design.md` because the report screenshot is unavailable (it never was); real endpoints only; essential tests; no backend change, no Stage 11, no commit or push; stop after F5. Done so.
Built: Runs tab: "Start a run" (approved plans only; one idempotency key per attempt, so a retry or double click returns the original run; opens the new run's report), run history (status, plan, duration, open report, cancel with confirmation, status filter, pagination, refreshes by itself while any run is active). Run report `/projects/:id/runs/:runId`: a verdict in words computed only from recorded results (`features/runs/verdict.js`: a finished run is never "passed" unless every expected check has a passed result; failures, errors, timeouts and anything that did not run are called out), key facts (status, checks with a result, duration, start, finish, time limit, last updated), progress bar, outcome bars with a written legend for checks and for individual test cases, a checks table with one row per runnable plan check (its recorded result, or "No result recorded"/"Waiting for a result" when there is none; filter by outcome, find by name, pagination; infrastructure outcomes such as "Could not start" carry their "not a test failure" note), batches, and the event trail. Result page `/projects/:id/runs/:runId/results/:resultId`: result facts, case table (outcome filter, messages and traces as plain text), evidence with plain-text viewer, download link and short hash. Honest states throughout: loading, empty, load failure, permission refusal, a failed refresh keeps the last data and says when it was taken, unavailable values read "Not available".
New shared pieces: `usePolledLoad` (polls while active, skips hidden tabs, keeps last good data), `OutcomeBar`, `EvidenceItem`/`EvidenceList` (moved from findings, now shared), formatters for durations and times; api: `listRunBatches`, `listRunEvents`, `evidenceUrl`. Removed: `RunsPanel` and `runs.css` (no longer used). Roadmap limits list no longer says the runs layout is planned.
Commands run (frontend/): `npm run lint` clean; `npx vitest run`: 17 files, 171 tests passed (three full runs, no failure); `npm run build` ok (JS 407 kB / 123 kB gzip). Tests (essential only): verdict rules; polling hook (continues while active, stops when done, keeps data through a failed refresh); start run with approved plans only and an idempotency key, retry with the same key, empty states, cancel only cancellable runs after confirmation; report (counts, "could not start" apart from failures, no-result rows, never-runnable plan items hidden, plan link, outcome filter, error state); result detail (cases, untrusted trace as text, evidence as text, download link, load failure); axe on the run history and report pages. The old RunsPanel tests were replaced by these.
NOT run / NOT verified: any browser view of the runs pages; a real run against the real backend (every test uses a fake API); how the page behaves while a real run changes state (polling is tested in isolation); screen reader and keyboard pass. The layout is Claude's reading of the design guide, not the owner's reference screenshot, and may need adjusting.
Known issues: Q98 (run list has no counts), Q99 (polling), Q100 (no coverage, comparison, export or live log).
Manual browser checklist for the owner (about 10 minutes, backend and worker running, an approved plan):
1. Runs tab: only approved plans are selectable; start a run. You land on its report; while it runs the status and counts update on their own and "last updated" changes.
2. Report: the verdict banner matches the results below it (a finished run with a failed or not-run check must not look like a pass). A check with no result says "No result recorded" (or "Waiting" while running). "Could not start" shows its note.
3. Filters: choose an outcome, search a check name; pagination appears only for long lists.
4. Open a check's Details: cases, messages and traces are plain text; "View" shows the log or report as text; "Download" saves the file.
5. Cancel a running run (confirmation first); the report shows "Cancelling" then the final state.
6. Phone width (about 390 px): no sideways page scroll, tables scroll inside their boxes, the summary figures wrap, dialogs fit.
7. Light, Dark and System; keyboard only through start, filters, a dialog and the result page.
Next action: owner review. Stopped after F5 as asked.

### Frontend - sign-in and request-access redesign (2026-10-23)
Date: 2026-10-23
Owner request: redesign Sign In, Sign Up and Request Access as a premium, minimal, book-inspired editorial layout (floating layered cards, subtle animated technical background, minimal top bar, no footer), keeping the authentication logic and not inventing a sign-up backend. No backend change, no Stage 11, no commit or push.
API inspected first: `auth` has login, logout, me, password, sessions; `admin` has list users and create/update user (admin only). There is no registration endpoint, so **Sign Up is the Request Access page** (accounts are created by an administrator) and `/signup` redirects to `/request-access`. This is the decision to confirm.
Built: `features/auth/AuthLayout` (editorial column with a book-style serif title, mono section tag with a double rule, an italic intro and three product principles; the form on a floating card with two sheets stacked behind it that settle in on load; "Sign in / Request access" tabs that keep `?next=`), `features/auth/AuthBackdrop` (fine grid plus twelve tiny pass/fail/skip/plus/bracket/diamond marks drifting slowly; transforms only; aria-hidden; no motion under reduced motion), `app/authPaths.js`, a minimal `Navbar` variant (brand and theme control only), and no footer on these routes (`AppShell`). `SignInPage` and `RequestAccessPage` rewritten on the layout; `SignInForm` and all sign-in logic, validation and error handling are unchanged. New `--serif` token (system serif stack, no web fonts). The request-access page is now three numbered steps plus a "what each role can do" disclosure and says plainly that it sends nothing.
Commands run (frontend/): `npm run lint` clean; `npx vitest run`: 18 files, 176 tests passed; `npm run build` ok (JS 409 kB / 124 kB gzip). New tests (`authpages.test.jsx`): both pages have the minimal bar, no footer and a decorative backdrop; other public pages keep footer and navigation; the current tab is marked and keeps `?next=`; no sign-up control exists; `/signup` lands on Request Access with no form fields. The existing sign-in, expiry, safe-redirect and axe tests still pass unchanged.
Checked visually (headless Chrome screenshots of the production build): sign-in at 1850 px and 390 px, request access at 1850 px, request access in dark mode. Layout, stacked card, grid and marks looked right; two polish items found and fixed (space under the card heading, and the blue info box made neutral to stay monochrome).
NOT verified: the animation itself in motion (screenshots are still frames); other browsers; the mobile request-access and dark sign-in pages were not screenshotted; screen reader and keyboard pass on the new layout.

### Frontend - account icon and sign-in-aware footer (2026-10-23)
Date: 2026-10-23
Owner feedback: the navbar's name link ("Name (super admin)") and Sign out button looked cluttered; make the account a proper icon and put Sign out on the account page; build a good footer that depends on whether the user is signed in, with a tagline. (The note's "hag" was read as "tag"/tagline; confirm if something else was meant.)
Changed: the navbar now shows the theme control and one round account icon (a link to `/account`, accessible name "Account: <name> (<role>)", tooltip "Your account"; on the collapsed phone menu it also shows the name as text). The navbar no longer has a name or a Sign out button. Sign out is a card on the Account page (it goes to the public home page first, then ends the session, so the route guard does not bounce the user to sign-in). New `app/Footer` replaces the old one-line footer: visitors get the brand, a serif tagline ("Test results you can trace back to evidence."), Product and "Get in" links (Home, Roadmap, Sign in, Request access), a "How to read this site" note and "Accounts are created by an administrator"; signed-in users get the same brand and tagline, Workspace links from the role-aware nav list (Projects, Approvals, Roadmap, Admin for admins), "Account and sessions", and "Signed in as <name> (<role>)". No social, legal or status links, because the product has none. Sign-in and request-access pages still have no footer.
Commands run (frontend/): `npm run lint` clean; `npx vitest run`: 19 files, 180 tests passed (twice); `npm run build` ok. Tests: the account control is one icon link with no Sign out button in the navbar; Sign out on the account page returns to the public home; the visitor footer and the signed-in footer differ as described (the sign-out and Admin-link tests were updated for the new places). Screenshots (headless Chrome, production build): the visitor footer at 1850 px and 390 px looked right.
NOT verified: the signed-in navbar and signed-in footer were not seen (a signed-in view needs a session or a backend, and a mock backend was not run); dark mode of the footer; the account icon at phone width; screen reader and keyboard pass.

### Frontend - brand logo (2026-10-23)
Date: 2026-10-23
Owner request: use the supplied shield "S" logo beside the project name and in the places it belongs.
Source checked: `~/Downloads/Shield S-Tech Verification Logo.png`, 1254 x 1254 RGBA with a real transparent background (left unmodified). Its dark navy would disappear on dark themes, so two renderings were derived (a one-off script, not kept in the repo): light (original colours) and dark (near-neutral dark pixels lightened; teal and grey kept), cropped to the artwork and padded square, resized to 128 px (about 13 kB and 10 kB), plus a 32 px favicon and a 180 px touch icon on a white rounded tile.
Used in: the navbar brand (full and quiet variants), the footer brand block, the favicon and the touch icon (`index.html`). New `components/BrandLogo` (+CSS) renders both and CSS shows the one matching the resolved theme; it is aria-hidden because the name is written beside it. The Vite template favicon was deleted. ADR-0009 decision 14.
Commands run (frontend/): `npm run lint` clean; `npx vitest run`: 19 files, 182 tests passed; `npm run build` ok (logo files about 23 kB in total, emitted as separate assets). Tests: the logo sits beside the name in the navbar and footer with empty alt text and a hidden wrapper, and on the quiet sign-in bar. Checked by screenshot (headless Chrome): light sign-in bar, dark navbar and dark footer.
NOT verified: the favicon and touch icon as shown in a browser tab or on a phone home screen (files generated and linked, not seen in a browser); the logo on the home hero (not used there by choice) or in any other place such as page titles or social previews.

