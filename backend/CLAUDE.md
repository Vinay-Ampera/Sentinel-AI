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

## Plans, approvals and policy rules (Stage 6)
- Test plans come only from `services/check_catalog.py`; never accept a command, risk level or approval flag from a request or a prompt. Risk and approval need are computed server-side (`services/policy.py`).
- Who may decide an approval is decided only by `services/policy.py` (`eligibility_denial`, `authorization_decision_denial`): explicit project grant, not the requester, org role bound for high/critical, project-designated approvers or managers. Never branch on roles in routes, and never give any role (Super Admin included) implicit project access: plans, runs, results and logs are reachable only through the project grant, or a Super Admin's audited, read-only, time-limited break-glass grant (`services/break_glass.py`). Break-glass is never used for decisions (`resolve_explicit_access`) and every request it serves is audited (`authorize_project` / `require_project_access` do this; use them). A refused decision must be audited before the error (`approvals._deny`).
- A submitted plan is frozen by DB triggers (migration 0003) and by `content_hash`; do not add code paths that edit planned tests after submit. Execution status is the only column that may change.
- Remote targets pass `authorizations.gate_reason` at plan time, at submit, and again in the worker before running (Stage 7). Production stays blocked unless the global policy and a Super Admin four-eyes authorization allow it.
- Routes addressed by plan/approval id (no `project_id` in the path) must authorize through `project_access.authorize_project` from the row's own project.

## Jobs and recovery rules (Stage 7)
- Runs come only from `services/runs.create_run` (approved plan, matching `content_sha256`, target gate, idempotency). A queue message carries only a batch id; never put commands, secrets or user input in a task. PostgreSQL decides every status: change run/batch status only through `repositories.runs.transition_*` (conditional on the expected status) via `services/job_state`, which also writes `job_events`.
- A worker may act only after `claim_batch` succeeds for its own message id, and must re-run `worker_runtime.revalidate` (starter access, plan hash, project state, target gate) before executing. Results are inserted idempotently; a worker that lost its lease stops writing.
- Executors implement `execution.interface.Executor`, poll `should_stop`, and never report a result they did not produce (the stub reports `skipped`). Cancellation never relies on Redis revocation.
- Retries are bounded and only for infrastructure failures; never auto-retry a test that already produced a result.

## Sandbox rules (Stage 8)
- Target-related execution happens only through `execution/docker_executor.py` and `docker_runner.py`. Never run a command, import, or extract an archive on the host; never add a bind mount, volume, device, Docker socket, `--privileged`, network, or environment pass-through to `execution/sandbox_spec.create_argv` (tests assert their absence).
- Commands come only from the fixed table `execution/commands.py` keyed by catalog check id; nothing from a request, plan parameter, prompt or sandbox output may reach a Docker argument. New runners need a threat-model update and Docker tests.
- Status comes from `docker inspect` and host timers, never from sandbox output. Output is untrusted: redact, cap, store under fixed names (`execution/evidence.py`).
- Every container carries `sentinel.sandbox=1` and the deployment scope label; cleanup/sweep filters on both. Always remove in `finally`.
- `JOB_EXECUTOR=stub` stays the default. Docker tests must use a unique scope and clean up only that scope.

