# Baseline quality commands (run from backend/). `make check` = lint + format check + types + tests.
.PHONY: install lint format format-check typecheck test check migrate migrate-sql current worker beat

install:
	poetry install
lint:
	poetry run ruff check .
format:
	poetry run ruff format .
format-check:
	poetry run ruff format --check .
typecheck:
	poetry run mypy
test:
	poetry run pytest
check: lint format-check typecheck test
current:
	poetry run alembic current
migrate-sql:
	poetry run alembic upgrade head --sql
migrate:
	poetry run alembic upgrade head
# Job queue (Stage 7): separate processes from the API. Need DATABASE_URL and REDIS_URL (env or backend/.env).
worker:
	poetry run celery -A sentinel_ai.jobs.worker worker -Q $${JOB_QUEUE_NAME:-sentinel-jobs} --concurrency 2 -l INFO
beat:
	poetry run celery -A sentinel_ai.jobs.worker beat -l INFO
