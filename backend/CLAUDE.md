# Backend Instructions (Python / FastAPI)

Read the root `CLAUDE.md` first. Current implementation status is in `docs/PROJECT_TRACKER.md`.

## Stack (initial decisions, see ADR-0001)
FastAPI, Poetry, PostgreSQL (durable source of truth), Celery + Redis (job delivery only), LangGraph + Gemini behind a provider service, Docker sandbox executor, versioned migrations, REST under `/api/v1`.

## Layout & layering
Code lives in `src/sentinel_ai/`: `api/` (routes, thin) → `services/` (application behavior) → `repositories/` (all DB access) → `models/`. Also `schemas/`, `core/` (config, security), `db/`, `jobs/` (Celery tasks), `orchestration/` (LangGraph graphs), `agents/` (narrow reasoning components), `execution/` (sandbox executor), `integrations/`. Create subfolders when a stage needs them; no empty placeholders.

## Rules
- Authentication/authorization checks are server-side on every protected endpoint and re-validated in workers before execution. A run/project ID alone is never proof of access.
- PostgreSQL holds run/job history. Redis is only a broker; never rely on Redis revocation as truth for cancellation.
- Target code runs only in the restricted sandbox. No public endpoint may execute arbitrary commands. Never pass platform secrets, DB/Redis credentials, the Docker socket, or host paths into sandboxes.
- Enforce target authorization, execution budgets, network-deny-by-default, and approval policies.
- Keep deterministic work out of LLM calls; validate structured model output; record usage.
- Validate all external input; redact secrets; do not log sensitive payloads.
- Config via environment variables; commit only `.env.example`.
- Schema changes only via versioned migrations.
- Do not install target-project dependencies in this Poetry environment.

## Commands (run from `backend/`; verified in Stage 1)
`poetry install`, `poetry run pytest`, `poetry run ruff check .`, `poetry run ruff format --check .`, `poetry run mypy`, `poetry run uvicorn sentinel_ai.main:create_app --factory --reload`, `make check`, `poetry run alembic ...` (migrations in `migrations/versions/`; URL from `DATABASE_URL` only (env, then untracked `backend/.env`, via `sentinel_ai.core.config`); DB integration tests need a disposable `TEST_DATABASE_URL` ending `_test`). Python 3.12.

## Authorization and intake rules
- Every new protected route depends on `api.deps.require_permission(...)` (role) and, for project-scoped routes, `require_project_access(level)` (scope); both must allow. Never read the session cookie directly.
- Uploaded archives are validated by `services/archive.py` and read only through bounded reads; never extract them to disk or execute/import anything from them. Storage keys are server-generated (`services/artifact_store.py`).
- Look up child resources (sources, analyses, ...) with `project_id`; an id alone is never proof of access.
