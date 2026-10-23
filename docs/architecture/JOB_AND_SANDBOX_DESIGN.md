# Job and Sandbox Design

> Status: **Stage 2 design.** Job model and state machine are final and enforced in the database (`state_transitions` table + trigger). The sandbox threat model is still required before untrusted code execution is enabled (Stage 8).

## Model
Run (`test_runs`) → batches (`test_batches`) → results (`test_results`, one per planned test per attempt). A run is created from an **approved** plan. Celery + Redis deliver work; **PostgreSQL is the source of truth for status**. Validate Celery behavior (retry, cancel, restart, duplicate delivery) with a proof of concept first (Q8).

## States (same vocabulary for runs and batches)
`queued`, `dispatched`, `running`, `cancel_requested`, `completed`, `failed`, `cancelled`, `timed_out`, `blocked`.
Terminal for runs: `completed`, `failed`, `cancelled`, `timed_out`. `blocked` = waiting on approval/authorization/policy.

## Valid transitions (enforced by `enforce_status_transition`)
| From | To | Meaning |
|---|---|---|
| queued | dispatched | Worker claimed it |
| queued | cancelled | Cancelled before start (immediate) |
| queued | blocked | Approval/authorization/policy missing at dispatch |
| queued | timed_out | Waited too long in queue |
| dispatched | running | Sandbox started |
| dispatched | failed | **Failed to start** (image/workspace/sandbox error) |
| dispatched | cancel_requested / cancelled / timed_out | Cancel or timeout before start |
| running | completed / failed / timed_out | Normal outcomes |
| running | cancel_requested | Cancel asked while running |
| cancel_requested | cancelled | Worker/executor confirmed termination |
| cancel_requested | completed / failed / timed_out | Finished (or timed out) before cancel took effect — recorded honestly |
| blocked | queued | Approval granted / authorization valid → re-queued |
| blocked | cancelled | Abandoned |
| **batches only:** failed, timed_out | queued | Retry (attempt+1, bounded by `max_attempts`) |
| **batches only:** dispatched, running | queued | Worker lost / restart recovery re-queue |

Anything else raises `invalid_state_transition` (API `409`). Runs are never retried in place; a rerun is a new run (`parent_run_id`). Run status is derived from batches: all `completed` → `completed`; any terminal failure with no retries left → `failed`; run `cancelled` only after all batches are terminal; run `timed_out` when its own `timeout_seconds` elapses (worker/beat check), which also cancels remaining batches.

## Retry policy
- Default `max_attempts = 1` (no retry). Infrastructure failures (`failed_to_start`, worker lost, broker redelivery) may retry up to 3 with exponential backoff and jitter.
- **Never auto-retry destructive/intrusive tests** or tests that already ran side effects; they require a new explicit approval.
- Idempotency by `(batch_id, planned_test_id, attempt)` unique result rows; duplicate delivery of a task whose result exists is a no-op.

## Cancellation
- `queued`/`blocked`: DB transition to `cancelled`, revoke the Celery task best-effort.
- `dispatched`/`running`: set `cancel_requested_at/by` and status `cancel_requested`; worker signals the executor to terminate the container; `cancelled` is recorded only after acknowledgement, or `timed_out`/`failed` with a reason after a grace period (default 30 s). Cleanup always runs.
- Cancel is idempotent and audited; results already collected are kept and marked.

## Timeouts
Run (`timeout_seconds`, default 3600, max 86400), batch (default 1800), queue wait (configurable). Enforced by the worker (hard kill of the container) and by a periodic reconciler for workers that died.

## Worker restart and reconciliation
A periodic reconciler finds batches in `dispatched`/`running` with no live heartbeat/worker and either re-queues (`worker_lost` event, bounded by attempts) or fails them with evidence, and finalizes runs whose batches are all terminal. All reconciler actions write `job_events`.

## Events and audit
Each transition writes a `job_events` row (append-only) with actor/worker and detail; security-relevant transitions (start, cancel, approval consumption) also write `audit_events`. Workers **revalidate** project access, plan approval, target authorization/expiry and policy immediately before executing.

## Developer-defined scripts
Stored as `script` artifacts, hashed; the executed hash is recorded on the result. They run only inside the sandbox profile of their adapter (`custom` category), with no network by default, default risk `medium`, requiring review/approval per policy; they cannot read platform secrets, the Docker socket, or other projects' workspaces.

## Sandbox minimum controls
Separate container per batch; non-root; drop all capabilities; seccomp/AppArmor where available; CPU/memory/pids/disk/time limits; read-only root FS with disposable workspace; no Docker socket, no platform secrets or env, no host home; network denied by default (allow-list only to an authorized target host/port when the plan requires it); no privileged containers; archive validation (traversal, symlinks, bombs, size/file-count); output size caps and secret redaction; audit scope, argv, image digests.

## Caveat
Docker is not a complete boundary against hostile code. Evaluate rootless Docker, gVisor, Kata, or disposable VMs (Q6) via a threat model before enabling untrusted execution. Until then execution stays disabled.

## Queue topology and protocol (implemented in Stage 7; ADR-0004)
- **Processes:** API (FastAPI), worker (`celery -A sentinel_ai.jobs.worker worker`), beat (`... beat`). `make worker` / `make beat` from `backend/`. Redis is only the broker (queue `sentinel-jobs`, JSON, no result backend, `acks_late`, `reject_on_worker_lost`, prefetch 1). Messages carry a batch id only.
- **Tasks:** `sentinel_ai.run_batch(batch_id)`, `sentinel_ai.dispatch_pending`, `sentinel_ai.reconcile` (beat every `JOB_RECONCILE_INTERVAL_SECONDS`, and once when a worker starts).
- **Run creation:** approved plan, unchanged `content_sha256`, target gate re-run, one active run per plan, `Idempotency-Key` returns the original run. The run, its batches (`JOB_BATCH_SIZE` tests each, in plan order) and `test_batch_items` are committed **before** anything is published.
- **Dispatch:** under an advisory lock, queued batches get a fresh `queue_task_id` (and an enqueue deadline of 5 leases) within the per-run (2) and global (4) limits, oldest run first; then the message is published with that id. A publish failure releases the id immediately; the reconciler releases an id that never produced a claim. Nothing is lost if Redis is down.
- **Claim:** `UPDATE ... WHERE status='queued' AND queue_task_id=:this_message_id AND not_before<=now()`. Only the latest dispatch can claim; duplicate, redelivered or stale messages claim nothing and exit (`noop`).
- **Worker:** claim -> revalidate (starter active and still allowed to run, project active, plan approved with the same hash, target gate per test) -> `running` -> per test: renew lease, check cancel/timeout in PostgreSQL, call `Executor.execute(request, should_stop)`, store an idempotent result (`UNIQUE(batch, test, attempt)`) -> settle batch -> derive run status -> dispatch the next batch. Revalidation failure fails the batch (`revalidation_failed`, results `blocked`); a policy-blocked test gets a `blocked` result; all blocked = `blocked_by_policy`.
- **Executor contract:** the stub records every test as `skipped` ("Not executed ... Stage 8"); it never reports pass/fail. A real executor must poll `should_stop` at least every lease/3 (this renews the lease and signals cancel/timeout/takeover) and implement `terminate`.
- **Leases:** `heartbeat_at`/`lease_expires_at` (60 s) are renewed on every poll. An expired lease means a lost worker. A worker whose batch was taken over stops writing (`lost`).
- **Reconciler:** advisory-locked and idempotent. Expired lease -> `worker_lost` event, then bounded re-queue (`attempt+1`, backoff with jitter) or `failed`/`worker_lost`; lost while `cancel_requested` -> `cancelled` with `termination_confirmed: false`; running past timeout + grace -> `timed_out`; `cancel_requested` unconfirmed past the grace -> `failed`/`cancel_unconfirmed`; run past its timeout or queued past `JOB_QUEUE_WAIT_SECONDS` -> remaining batches cancelled/timed out and the run `timed_out`; runs with all batches terminal are finalized. Tests not yet run are recorded (`cancelled`/`skipped`, "Not run: ...") so none is silently missing.
- **Restart behavior:** after a worker restart its unacknowledged message may be redelivered later; it is harmless (the batch was re-dispatched with a new id). Recovery never depends on the broker. The first lease must expire (60 s by default) before a lost batch is re-queued. Sandbox cleanup of a lost worker is Stage 8 (Q55).
- **Events/audit:** every transition writes `job_events`; `run.create`, `run.cancel`, `run.start`, `run.finish` (and refused starts) write `audit_events`.

## Sandbox executor (implemented in Stage 8; ADR-0005, SANDBOX_THREAT_MODEL.md)
- `JOB_EXECUTOR=docker` swaps the stub for `DockerSandboxExecutor`. Per planned test: fixed command by check id (`execution/commands.py`; only `sandbox_smoke` today, others `skipped`), network checks `blocked`, the worker supplies a project-scoped `WorkspaceRef`, the executor re-reads the archive once, checks its SHA-256 and headers, and streams exactly those bytes to a locked-down container over stdin.
- Result mapping (from `docker inspect` and host timers only): exit 0 `passed`; other exit `failed`; 70 archive refused `error`; OOM `error`; timeout `timed_out`; cancel `cancelled`; create/start failure `failed_to_start` (retryable by Stage 7 rules).
- Evidence per test: `stdout.log`, `stderr.log` (`log`), `manifest.json` (`report`: limits, image id, container configuration as the daemon reports it, exit state, durations). Stored under `projects/{project}/runs/{run}/results/{result}/` with SHA-256 in `artifacts`.
- Cancel/timeout: `should_stop` is polled every 0.5 s (also renews the lease); the container is killed and removed; a host deadline (timeout + 5 s) covers a frozen in-container runner. Lost or stuck workers: the reconciler calls `terminate(batch)` and the janitor sweeps leaked containers by age within the deployment scope.

## Running a project's tests (implemented in Stage 9; ADR-0006)
- `pytest_unit` is in the fixed command table with `runs_project_code=True`: it is `blocked` (no container) unless `SANDBOX_ALLOW_PROJECT_CODE` is set. The in-image runner prints the JUnit file as a nonce-framed block at the end of stdout; the host keeps a stdout tail buffer, takes the last valid frame, parses it defensively (`execution/junit.py`) and stores cases in `test_case_results`.
- Status mapping for pytest: exit 0 `passed`, 1 `failed`, 5 `skipped` (no tests), other `error`; infrastructure states as before. A report can never change the status.
- The worker re-checks ownership after every execution, records a test that hit its own timeout and continues with the next one, writes explicit `not_run` results for tests that never started, and stores cases then evidence (never losing the committed result).
- API: `GET /test-runs/{run}/results/{result}` (result + cases + evidence descriptors), `GET /artifacts/{id}/content` (run evidence only), progress includes `cases_by_status`.

## Remaining TODO (Stage 10+)
Dependency path for projects with third-party imports (Q66), allow-listed egress and localhost-target reach (Q26/Q60), browser tests (Playwright, Q69), JavaScript runners, evidence retention (Q70), stronger runtime tested for real (Q59).
