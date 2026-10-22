# Sentinel AI

Evidence-driven application quality platform: analysis, risk-gated test planning, sandboxed execution, security/accessibility checks, observability alerts, failure investigation, regression-test proposals, and fix verification.

**Status:** Stage 1 scaffold — hello-world backend health endpoint and frontend page only; no application features. See `docs/IMPLEMENTATION_PLAN.md` for progress and `docs/OPEN_QUESTIONS.md` for unresolved items.

## Docs
- `docs/Sentinel_AI_Full_Project_Blueprint.md` (requirements), `docs/IMPLEMENTATION_PLAN.md` (plan and tracker)
- `docs/architecture/`, `docs/decisions/`, `docs/SECURITY_AND_SAFETY.md`, `docs/TEST_STRATEGY.md`, `docs/DATABASE_SCHEMA.md`

## Quickstart
Prerequisites: Python 3.12, Poetry, Node.js 24, Docker (later stages).
```bash
cd backend && poetry install && poetry run pytest      # backend checks
cd frontend && npm install && npm test && npm run build # frontend checks
```
See `backend/README.md` and `frontend/README.md` for run commands.
