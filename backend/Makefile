# Baseline quality commands (run from backend/). `make check` = lint + format check + types + tests.
.PHONY: install lint format format-check typecheck test check migrate migrate-sql current worker beat sandbox-image advisories scanner-image zap-image

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

# Stage 10: the dependency audit's advisory data. The ONLY step that needs the network (OSV dumps
# for PyPI and npm); run it from an operator machine, then rebuild the image. Re-run regularly:
# the audit refuses to run on data older than DEPENDENCY_ADVISORY_MAX_AGE_DAYS (default 30).
advisories:
	python3 ../sandbox/advisories.py

sandbox-image:
	poetry run python ../sandbox/vendor.py
	docker build -t sentinel-sandbox-runner:stage8 \
	  --build-arg ADVISORY_FETCHED_AT=$$(python3 -c "import json,pathlib;m=json.loads(pathlib.Path('../sandbox/advisories/meta.json').read_text()) if pathlib.Path('../sandbox/advisories/meta.json').exists() else {};print(min((v['fetched_at'] for v in m.values()),default='none'))") \
	  ../sandbox

# Semgrep needs network at BUILD time only (pip install). Pin the release: make scanner-image SEMGREP_VERSION=...
# If Docker's bridge has no internet, add DOCKER_BUILD_ARGS=--network=host (build step only; run time stays --network none).
scanner-image:
	docker build $(DOCKER_BUILD_ARGS) -f ../sandbox/Dockerfile.semgrep -t sentinel-scanner-runner:stage10 \
	  --build-arg SEMGREP_VERSION=$(SEMGREP_VERSION) ../sandbox

# ZAP: see sandbox/Dockerfile.zap (unverified) and the ZAP section of SANDBOX_THREAT_MODEL.md.
zap-image:
	docker build -f ../sandbox/Dockerfile.zap -t sentinel-zap-runner:stage10 \
	  --build-arg ZAP_BASE=$(ZAP_BASE) ../sandbox
