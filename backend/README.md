# Sentinel AI — Backend

FastAPI service. See `CLAUDE.md`, `../docs/IMPLEMENTATION_PLAN.md` (stages) and `../docs/PROJECT_TRACKER.md` (current status).

## Prerequisites
Python 3.12, Poetry.

## Commands
```bash
poetry install                 # install dependencies
poetry run uvicorn sentinel_ai.main:create_app --factory --reload   # http://127.0.0.1:8000/api/v1/health/ready
poetry run pytest              # tests
poetry run ruff check .        # lint
poetry run ruff format --check .
poetry run mypy                # type check
poetry run alembic --help      # migrations (no schema yet; configured in Stage 3)
```

## Environment variables
Names, defaults, and placeholders are in `.env.example`; real values go only in the untracked `backend/.env` (never commit or paste secrets).

| Variable | Needed for | Secret |
|---|---|---|
| `DATABASE_URL` | Alembic and the app (database `sentinel-ai`) | yes (contains password) |
| `TEST_DATABASE_URL` | Integration tests; **must** name a disposable database ending in `_test` | yes |
| `SESSION_TOKEN_PEPPER` | Sessions (>= 32 random chars; auth endpoints return 503 without it) | yes |
| `GEMINI_API_KEY` | LLM calls (Stage 11) | yes |
| `REDIS_URL` | Readiness probe now; Celery (Stage 7) | yes if it has a password |
| `GEMINI_MODEL`, `LLM_*` (limits, prices, timeouts, retries; see `docs/architecture/AGENT_WORKFLOWS.md`) | LLM gateway (Stage 11) | no (defaults apply; `GEMINI_MODEL` needed to enable) |
| `RATE_LIMIT_BACKEND` (`memory` default, or `redis`: limits shared by all API processes through `REDIS_URL`) | API rate limits (Stage 12) | no |
| `ALERT_EVALUATION_*`, `EVENT_PURGE_*` (scheduled jobs run by `celery beat`; purge is off by default) | Alert evaluation and retention (Stage 12) | no |
| `TRUSTED_PROXY_CIDRS` (comma-separated networks of reverse proxies whose `X-Forwarded-For` is trusted; empty by default) | Client address behind a proxy (ingestion throttling and audit) | no |
| `INGEST_*`, `EVENT_*`, `ALERT_OPEN_CAP` (request and event limits, rate limits, quotas, retention days, ingest key lifetime; see `docs/decisions/ADR-0011-observability-alerts-and-failure-to-test-loop.md`) | Observability ingestion and alerts (Stage 12) | no (defaults apply) |
| Others (`APP_ENV`, `SESSION_*`, `ARTIFACT_*`, `UPLOAD_*`, `ZIP_*`, `CORS_ALLOWED_ORIGINS`) | later stages | no |

## Configuration loading (Stage 3)
`sentinel_ai.core.config` loads settings from **process environment variables first, then `backend/.env`** (path-independent; override the file with `SENTINEL_ENV_FILE`). Both the app and Alembic use it, so `DATABASE_URL` in `backend/.env` is all you need: no `set -a` step. Settings are validated at startup (`create_app()` / Alembic); a missing or invalid value stops with a message listing the variable names and reasons, never the values. Examples: `DATABASE_URL: is required`, `LOG_LEVEL: Input should be 'DEBUG', ...`. Secrets are `SecretStr` and are masked in `repr`, logs, and `/health/ready`. In `APP_ENV=production`, `SESSION_TOKEN_PEPPER` (>= 32 chars) and `SESSION_COOKIE_SECURE=true` are mandatory. `postgresql://` URLs are used with the psycopg 3 driver automatically.

## Health endpoints
- `GET /api/v1/health` and `/health/live`: liveness only (`{"status":"ok"}`).
- `GET /api/v1/health/ready`: `200`/`503` with `{"status": "ready|not_ready", "checks": {"database": ok|unavailable, "migrations": ok|pending|unknown, "redis": ok|unavailable}}`. Ready = database reachable **and** at the newest Alembic revision. Redis is reported but does not fail readiness (Q31). Only status words are returned; no URLs, hosts, credentials, or exception text.

## Local services (Docker Compose, repo root)
`docker-compose.yml` provides Redis and, optionally, a **separate** throw-away PostgreSQL (profile `local-db`, port 5433, own volume). Your existing local `sentinel-ai` database is not managed by Compose.
```bash
cp .env.example .env            # repo root; set REDIS_PASSWORD (and POSTGRES_PASSWORD for local-db)
docker compose up -d redis                    # Redis on 127.0.0.1:6379 (password required)
docker compose --profile local-db up -d       # + dev PostgreSQL on 127.0.0.1:5433
docker compose ps && docker compose down      # status / stop (data volume kept)
```
Compose refuses to start without `REDIS_PASSWORD`; there are no default passwords. Set `REDIS_URL=redis://:PASSWORD@localhost:6379/0` in `backend/.env`.

## Job queue (Stage 7)
Celery + Redis deliver batches to a **separate worker process**; PostgreSQL is the source of truth for every status, and Redis is only the broker. By default (`JOB_EXECUTOR=stub`) runs record each test as `skipped` ("Not executed") and no target code runs; the Docker sandbox below is an explicit opt-in.
```bash
docker compose up -d redis      # needs REDIS_PASSWORD (root .env); set REDIS_URL in backend/.env
make worker                     # poetry run celery -A sentinel_ai.jobs.worker worker -Q sentinel-jobs --concurrency 2
make beat                       # periodic reconcile + dispatch (run exactly one beat)
```
Run the API as usual. Optional tuning (defaults in parentheses): `JOB_QUEUE_NAME` (sentinel-jobs), `JOB_BATCH_SIZE` (10), `JOB_MAX_CONCURRENT_BATCHES_PER_RUN` (2), `JOB_MAX_CONCURRENT_BATCHES` (4), `JOB_LEASE_SECONDS` (60), `JOB_CANCEL_GRACE_SECONDS` (30), `JOB_MAX_ATTEMPTS` (1, max 3), `JOB_RETRY_BACKOFF_SECONDS` (5), `JOB_BATCH_TIMEOUT_SECONDS` (1800), `JOB_RUN_TIMEOUT_SECONDS` (3600), `JOB_QUEUE_WAIT_SECONDS` (3600), `JOB_RECONCILE_INTERVAL_SECONDS` (30). If the broker is down, `POST /projects/{id}/test-runs` still returns `202` and the batch is dispatched later by beat. After a worker crash, wait for the lease to expire (default 60 s) and the reconciler re-queues or fails the batch visibly (`GET /test-runs/{id}/events`). Design: `docs/architecture/JOB_AND_SANDBOX_DESIGN.md`.
Broker tests: set `TEST_DATABASE_URL` (a `*_test` database) and `TEST_REDIS_URL` (a disposable Redis) to run `tests/integration/test_celery_broker.py`; otherwise they skip.

## Sandbox (Stage 8)
Checks run in disposable Docker containers only when you opt in with `JOB_EXECUTOR=docker` (default `stub`). Containers have no network, a read-only root filesystem, no capabilities, a non-root user and CPU/memory/process/disk/time limits; the source archive is streamed over stdin and nothing from the host is mounted. Two checks have runners: `sandbox_smoke` (unpacks the uploaded ZIP and counts files; no project code runs) and `pytest_unit` (runs the **project's own pytest suite**; off by default, see below). Other checks are recorded as skipped.
```bash
make sandbox-image                                  # vendors pytest and Bandit from poetry.lock, bakes in sandbox/advisories, builds sentinel-sandbox-runner:stage8 (no network)
make advisories                                     # OPERATOR step, needs network: downloads OSV advisory data for the offline dependency audit
make scanner-image SEMGREP_VERSION=<pin>            # needs network at build time: base image + Semgrep + bundled local rules (unverified, ADR-0008)
make zap-image ZAP_BASE=<reviewed image>            # ZAP runner (unverified; read the ZAP checklist in SANDBOX_THREAT_MODEL.md first)
JOB_EXECUTOR=docker make worker                      # the worker host needs a Docker daemon
poetry run pytest tests/integration/test_sandbox_docker.py   # Docker tests (skip if no daemon or image)
```
Settings (defaults): `SANDBOX_IMAGE`, `SANDBOX_RUNTIME` (empty = runc; e.g. `runsc`), `SANDBOX_SCOPE` (default; cleanup only touches containers with this label), `SANDBOX_CPUS` (1), `SANDBOX_MEMORY_MB` (512), `SANDBOX_PIDS` (128), `SANDBOX_WORKSPACE_MB` (128), `SANDBOX_TMP_MB` (16), `SANDBOX_MAX_EXTRACT_MB` (96), `SANDBOX_MAX_FILE_MB` (32), `SANDBOX_TEST_TIMEOUT_SECONDS` (300), `SANDBOX_OUTPUT_CAP_BYTES` (1048576). Running a project's own tests (`pytest_unit`) executes untrusted code, so it is **off** until you choose: `JOB_EXECUTOR=docker` plus `SANDBOX_ALLOW_PROJECT_CODE=true` plus either `SANDBOX_RUNTIME=runsc` (gVisor/Kata) or `SANDBOX_ACCEPT_SHARED_KERNEL=true` (a written acceptance of plain-Docker shared-kernel risk). Without them the check is recorded as `blocked` and no container starts. The sandbox is offline with only the standard library and pytest: projects importing other packages report an `error` that says so. Results: `GET /test-runs/{id}/results/{result}` (cases and evidence) and `GET /artifacts/{id}/content` (evidence download, project-authorized). Run workers on a dedicated host: access to the Docker daemon is root-equivalent (see `docs/architecture/SANDBOX_THREAT_MODEL.md`).

## Quality commands
`make check` (from `backend/`) runs `ruff check`, `ruff format --check`, `mypy`, and `pytest`; individual targets: `lint`, `format`, `format-check`, `typecheck`, `test`, `current`, `migrate-sql`, `migrate`.

## Database setup (local and cloud)
`DATABASE_URL` is the **only** database setting: Alembic (`migrations/env.py`) and, from Stage 3, the app both read it. `alembic.ini` has an empty `sqlalchemy.url` on purpose. Real values live in the untracked `backend/.env` (git-ignored; only `.env.example` is committed). The frontend has its own separate `frontend/.env` (public `VITE_*` values only, never DB settings).

- **Local (existing database `sentinel-ai`):** `DATABASE_URL=postgresql://USER:PASSWORD@localhost:5432/sentinel-ai`. Application tables go in `public`, authentication tables in `app_user` (created by the migrations; nothing else needs creating by hand). Special characters in the password must be URL-encoded.
- **Later, cloud (RDS, Cloud SQL, Supabase, Neon, ...):** change only `DATABASE_URL`, e.g. `postgresql://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require` (use `verify-full` plus `sslrootcert` where the provider supplies a CA). No code or migration change. Use a least-privilege migration role, keep the password in the platform's secret store (not a committed file), and run `alembic upgrade head` once against the new database.
- Use a *different*, disposable database (name ending `_test`) for `TEST_DATABASE_URL`; never the real one.

## Database migrations (Alembic)
```bash
poetry run alembic current                       # applied revision
poetry run alembic upgrade head --sql            # print DDL without running it
poetry run alembic upgrade head                  # apply (uses DATABASE_URL)
poetry run alembic downgrade -1                  # roll back one revision (drops that revision's tables!)
TEST_DATABASE_URL=... poetry run pytest tests/integration   # disposable DB only
```
Schema design: `docs/DATABASE_SCHEMA.md`. Back up (`pg_dump`) before upgrading or downgrading a database that holds real data.

## Authentication (Stage 4)
Create the first Super Admin (password is prompted, never passed as an argument): `poetry run python -m sentinel_ai.cli create-super-admin --email you@example.com --display-name "Your Name"`. Endpoints: `POST /api/v1/auth/login|logout|password`, `GET /api/v1/auth/me|sessions`, `DELETE /api/v1/auth/sessions/{id}`, `GET /api/v1/users`, `POST /api/v1/admin/users`, `PATCH /api/v1/admin/users/{id}`. State-changing requests need the `X-CSRF-Token` returned by login / `/auth/me`. Optional tuning: `SESSION_IDLE_MINUTES`, `SESSION_ABSOLUTE_HOURS`, `LOGIN_MAX_FAILURES`, `LOGIN_LOCKOUT_MINUTES`, `LOGIN_IP_MAX_ATTEMPTS_PER_MINUTE`.

## Projects and analysis (Stage 5)
`POST /api/v1/projects`, `GET /projects[/{id}]`, `PATCH /projects/{id}`, `POST /projects/{id}/archive`, members at `/projects/{id}/members[/{user_id}]`. Upload a ZIP with `POST /projects/{id}/sources/zip?name=NAME` (body = the raw ZIP, `Content-Type: application/zip`, plus `X-CSRF-Token`), e.g. `curl -b cookies.txt -H "X-CSRF-Token: $CSRF" -H "Content-Type: application/zip" --data-binary @src.zip "http://localhost:8000/api/v1/projects/$PID/sources/zip?name=src"`. Then `POST /projects/{id}/analyses {"source_id": ...}`; read results with `GET /projects/{id}/analyses` or `GET /analyses/{id}`. Uploads are stored under `ARTIFACT_STORAGE_DIR` (default `backend/artifacts`, git-ignored) and limited by `UPLOAD_MAX_MB`, `ZIP_MAX_UNCOMPRESSED_MB` and `ZIP_MAX_FILES`. Archives are never extracted or executed.

Other source types are registered with `POST /api/v1/projects/{id}/sources` (JSON): `{"source_type":"git_repository","name":"repo","git_url":"https://github.com/org/repo.git","git_ref":"main"}`, `{"source_type":"localhost_url","name":"dev","target_url":"http://localhost:3000"}`, `{"source_type":"remote_url","name":"stg","target_url":"https://staging.example.com","environment":"staging"}`. Only a descriptor is stored: nothing is cloned, resolved or probed, production targets are refused, and analysing these types returns `analysis_not_available` until the sandbox and target-authorization stages exist. Remove abandoned upload temp files with `poetry run python -m sentinel_ai.cli purge-temp`.

| Variable | Default | Purpose |
|---|---|---|
| `ARTIFACT_STORAGE_BACKEND` | `local` | only `local` is implemented |
| `ARTIFACT_STORAGE_DIR` | `./artifacts` (relative to `backend/`) | where uploaded ZIPs are stored |
| `UPLOAD_MAX_MB` | `100` | maximum ZIP upload size |
| `ZIP_MAX_UNCOMPRESSED_MB` | `500` | maximum declared uncompressed size |
| `ZIP_MAX_FILES` | `20000` | maximum entries in an archive |
| `LOGIN_IP_MAX_ATTEMPTS_PER_MINUTE` | `20` | per-IP sign-in rate limit |

