# Backend Instructions (Python / FastAPI)

Read the root `CLAUDE.md` first. Status: Stage 1 scaffold (health endpoint only; no features).

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
`poetry install`, `poetry run pytest`, `poetry run ruff check .`, `poetry run ruff format --check .`, `poetry run mypy`, `poetry run uvicorn sentinel_ai.main:app --reload`, `poetry run alembic ...` (Alembic initialized in `migrations/`; DB URL configured in Stage 3). Python 3.12.
