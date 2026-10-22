# Sentinel AI

Evidence-driven application quality platform: analysis, risk-gated test planning, sandboxed execution, security/accessibility checks, observability alerts, failure investigation, regression-test proposals, and fix verification.

**Status:** see `docs/PROJECT_TRACKER.md` for progress, `docs/IMPLEMENTATION_PLAN.md` for the stage list, and `docs/OPEN_QUESTIONS.md` for unresolved items.

## Docs
- `docs/Sentinel_AI_Full_Project_Blueprint.md` (requirements), `docs/IMPLEMENTATION_PLAN.md` (stage list, requirements, acceptance criteria), `docs/PROJECT_TRACKER.md` (detailed progress)
- `docs/architecture/`, `docs/decisions/`, `docs/SECURITY_AND_SAFETY.md`, `docs/TEST_STRATEGY.md`, `docs/DATABASE_SCHEMA.md`

## Quickstart
Prerequisites: Python 3.12, Poetry, Node.js 24, Docker (later stages).
```bash
cd backend && poetry install && make check             # backend lint/format/types/tests
cd frontend && npm install && npm test && npm run build # frontend checks
```
Copy the backend example env file to `backend/.env` and set `DATABASE_URL`. Local Redis/Postgres via `docker-compose.yml`. See `backend/README.md` (configuration, health, migrations, Compose) and `frontend/README.md`.
