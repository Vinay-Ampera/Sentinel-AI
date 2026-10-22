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

## Remaining TODO (Stage 7/8)
Queue topology and task names, executor interface, artifact flow detail, threat model, residual risks.
