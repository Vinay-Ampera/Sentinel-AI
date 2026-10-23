# ADR-0004: Job dispatch, claim and recovery (Stage 7)

Status: Accepted (owner approved the design on 2026-10-23)

## Context
ADR-0001 chose Celery + Redis for job delivery and PostgreSQL as the source of truth. Celery gives at-least-once delivery, so a message can arrive twice, late, or after its batch was cancelled or recovered. Stage 7 must make cancellation, retries, timeouts and worker restarts safe without trusting the broker. Execution itself is a stub until Stage 8.

## Decision
1. **State lives in PostgreSQL** (migration 0002 state machine). Messages carry a batch id only.
2. **Commit, then publish.** Runs and batches are committed before anything is sent. The dispatcher stamps each batch with a fresh `queue_task_id` under an advisory lock and within concurrency limits, then publishes a message with that id. A failed publish releases the id; an id that never produced a claim is released by the reconciler after an enqueue deadline.
3. **Claim by latest dispatch.** A worker moves `queued -> dispatched` only with `queue_task_id` equal to its message id. Duplicate, redelivered and stale messages claim nothing.
4. **Leases, not broker state, detect lost workers.** Workers renew `lease_expires_at` while polling `should_stop`; an advisory-locked, idempotent reconciler re-queues (bounded) or fails batches with expired leases and times out overruns.
5. **Cancellation is a DB state** (`cancel_requested`); the worker reads it, calls `Executor.terminate`, and reports `cancelled` or `failed/cancel_unconfirmed`. Celery revoke is not used.
6. **Revalidation in the worker** of the starter's access, plan approval and hash, project state and the target gate, immediately before executing.
7. **Honest results.** The stub records `skipped` ("Not executed"); unrun tests of a stopped batch are recorded as `cancelled`/`skipped`. Retries are bounded (default 1 attempt, max 3), only for infrastructure failures, and never repeat a test that already has a result.
8. **Additive migration 0005**: lease/heartbeat/backoff columns and `test_batch_items`.

## Consequences
- Duplicate delivery and worker restarts are safe by construction and were tested, including a SIGKILL of a real worker with a real broker.
- A lost batch is recovered only after its lease expires (default 60 s).
- Termination of a lost worker's sandbox is unconfirmed by design; Stage 8 adds cleanup by label (Q55).
- Beat must run exactly once for periodic dispatch/reconcile; the advisory locks make an accidental second beat harmless but wasteful.
- Analysis stays synchronous (Q52) and rerun is not built (Q53).
