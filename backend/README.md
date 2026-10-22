# Sentinel AI — Backend

FastAPI service. Status: Stage 1 scaffold (health endpoint only). See `CLAUDE.md` and `../docs/IMPLEMENTATION_PLAN.md`.

## Prerequisites
Python 3.12, Poetry.

## Commands
```bash
poetry install                 # install dependencies
poetry run uvicorn sentinel_ai.main:app --reload   # http://127.0.0.1:8000/api/v1/health
poetry run pytest              # tests
poetry run ruff check .        # lint
poetry run ruff format --check .
poetry run mypy                # type check
poetry run alembic --help      # migrations (no schema yet; configured in Stage 3)
```

## Environment variables
None required yet. See `.env.example`; `.env` is untracked.
