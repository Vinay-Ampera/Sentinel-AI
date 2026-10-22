# File Structure

> Status: target layout from `IMPLEMENTATION_PLAN.md` §3. Folders are created when their stage begins; no empty placeholders.

## Top level
```text
.github/workflows/   CI (Stage 16)
backend/             FastAPI platform (src/sentinel_ai/, tests/, migrations/)
frontend/            React + Vite + TS app
docs/                architecture, decisions, cross-cutting design
docker-compose.yml   local dev services (Stage 3)
docker-compose.prod.yml  production REFERENCE only, not production-ready
CLAUDE.md, settings.json, README.md, .gitignore
```

## Backend responsibilities (`backend/src/sentinel_ai/`)
| Folder | Responsibility |
|---|---|
| `api/` | Thin HTTP routes, request validation, authz dependencies |
| `services/` | Application behavior |
| `repositories/` | All database access |
| `models/`, `schemas/` | ORM models; request/response schemas |
| `core/`, `db/` | Config, security primitives; engine/session |
| `jobs/` | Celery task definitions, queue coordination |
| `orchestration/` | LangGraph graphs and state transitions |
| `agents/` | Narrow reasoning components |
| `execution/` | Sandbox executor interface |
| `integrations/` | External tools/providers (Gemini, Semgrep, ZAP...) |

**Dependency direction:** `api → services → repositories → models/db`. `services` may call `jobs`, `orchestration`, `execution`, `integrations`. `repositories` never import `services`/`api`. `agents` never execute shell or bypass services. Target project code never runs in the API process.

## Frontend responsibilities (`frontend/src/`)
`app/` bootstrap, `routes/` routing, `components/` shared UI, `features/` per product area, `hooks/`, `services/` API client (only place that calls the backend), `types/`, `utils/`. Direction: `routes → features → components/hooks/services`; features do not import each other's internals.

## Docs
`docs/architecture/` (this folder), `docs/decisions/` (ADRs), plus `DATABASE_SCHEMA.md`, `SECURITY_AND_SAFETY.md`, `TEST_STRATEGY.md`, `IMPLEMENTATION_PLAN.md` (tracker).

## Known inconsistency
The plan's structure rules mention `backend/execution/`, while the tree shows `backend/src/sentinel_ai/execution/`. This repo uses the latter (OPEN_QUESTIONS Q4).
