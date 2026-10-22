# Job and Sandbox Design

> Status: SKELETON capturing plan §7–§8 requirements. A full threat model is required before untrusted code execution is enabled (Stage 8).

## Jobs (decided direction)
- Celery + Redis for delivery; PostgreSQL is the durable status source. Validate with a proof of concept (retries, cancellation, worker restart, duplicate delivery) first.
- Run → batches → test cases. Bounded retries with backoff; no auto-retry of destructive tests; idempotency by run/batch/test IDs.
- Cancellation: queued → remove and mark in DB; running → durable cancel request, worker asks executor to terminate; confirm only after acknowledgement or recorded timeout. Cleanup always runs.
- Worker restart: reconcile stuck runs (resume, retry, or mark interrupted with evidence).

## Sandbox minimum controls
Separate containers; non-root; drop capabilities; seccomp/AppArmor where available; CPU/memory/pids/disk/time limits; disposable workspace; no Docker socket, no platform secrets, no host home; network denied by default; no privileged containers; archive validation (traversal, symlinks, bombs); redact output; audit scope, commands, image versions.

## Caveat
Docker is not a complete boundary against hostile code. Evaluate rootless Docker, gVisor, Kata, or disposable VMs (OPEN_QUESTIONS Q6).

## TODO
Queue topology, state-transition table, executor interface, artifact flow, threat model, residual risks.
