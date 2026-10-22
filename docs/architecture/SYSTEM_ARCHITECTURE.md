# System Architecture

> Status: DRAFT derived from `IMPLEMENTATION_PLAN.md` §6. Nothing here is implemented. Not yet cross-checked against the blueprint.

## Components
1. **React frontend** — projects, plan review, progress, findings, alerts, history, chat.
2. **FastAPI backend** — authn/authz, project/plan/run/evidence APIs (`/api/v1`).
3. **PostgreSQL** — durable source of truth: users, access, projects, plans, runs, batches, results, findings, approvals, alerts, audit.
4. **Redis** — Celery broker only; not a history store.
5. **Celery workers** — claim queued jobs, revalidate authorization, drive lifecycle.
6. **Sandbox executor** — restricted Docker containers for target code and testing tools.
7. **LangGraph orchestration** — conditional reasoning workflows (analysis, planning, investigation, verification).
8. **Gemini provider service** — centralized model calls with timeouts, token limits, usage recording.
9. **Artifact storage interface** — local directory in dev; production store TBD.
10. **Telemetry** — OpenTelemetry-compatible correlation where targets are instrumented.

## Trust zones
| Zone | Contents | Trust |
|---|---|---|
| Browser | Frontend | Untrusted client |
| Platform | API, workers, Postgres, Redis | Trusted; holds secrets |
| Sandbox | Target code, test tools | Untrusted; no platform secrets, no Docker socket, network denied by default |
| External | Gemini API, scan targets | Separate; targets require authorization |

Repository files, logs, prompts, and tool output are untrusted data everywhere.

## Normal run flow
Request → authorize (identity, project, target scope, policy) → deterministic analysis/plan (LLM only if needed) → user reviews plan and risk → low-risk may auto-run, high-risk waits for approval → persist run/batches → enqueue → worker revalidates → sandbox runs approved commands → collect/redact artifacts → update Postgres → classify findings → optional AI investigation → optional regression-test proposal → fix verification → UI shows evidence.

## Run lifecycle
`QUEUED → DISPATCHED → RUNNING → COMPLETED | FAILED | CANCELLED | TIMED_OUT | BLOCKED`, plus `CANCEL_REQUESTED`. Transitions validated and persisted.

## Boundaries
- LangGraph coordinates reasoning; long-running execution stays in workers/sandbox.
- No endpoint exposes arbitrary command execution.
- Observability claims limited to what is actually instrumented/ingested.

## Open items
Auth mechanism, sandbox isolation level, artifact store, deployment topology — see `docs/OPEN_QUESTIONS.md`.
