# ADR-0005: Docker sandbox baseline (Stage 8)

Status: Accepted (owner approved the threat model and plan on 2026-10-23). Resolves Q6 (baseline), Q26 (deferred), Q55.

## Context
Stage 7 delivers runs through an `Executor` interface with a stub. Stage 8 must execute checks only inside isolated, resource-limited, network-denied containers, collect evidence safely, and clean up on every path, without running target code on the host.

## Decision
1. **Hardened Docker (runc) is the baseline**, with `SANDBOX_RUNTIME` to substitute gVisor/Kata later. Running genuinely untrusted project code in production requires a stronger runtime or disposable VMs (threat model residual risk 2).
2. **Docker CLI with fixed argument vectors** (no SDK, no shell). The worker passes the CLI a minimal environment. Container recipe: `--network none`, read-only rootfs, `--cap-drop ALL`, `no-new-privileges`, user `65534:65534`, CPU/memory (no swap)/pids/ulimit/tmpfs limits, no mounts/devices/socket/env pass-through, `--init`, `--ipc none`, `--log-driver none`, labels for run/batch/scope.
3. **The source archive travels over stdin**, never as a mounted path. A trusted in-image runner (`sandbox/entry.py`) extracts it with strict checks and runs a command with its own timeout; the host also keeps a deadline.
4. **Commands come only from a server-side table** keyed by catalog check id (`execution/commands.py`). Stage 8 has one: `sandbox_smoke` (a new low-risk, developer-selectable, non-automatic check that unpacks the archive and counts files without running project code). Unmapped checks are `skipped`; network checks are `blocked`.
5. **Network is always disabled.** Allow-listed egress and localhost-target reach (Q26) are deferred to Stage 9 with the dependency story.
6. **Status comes from `docker inspect`**, never from output. Evidence is stdout, stderr and a host-generated manifest, redacted, capped, and stored as `log`/`report` artifacts with SHA-256 (no new migration). Result files such as JUnit XML arrive in Stage 9.
7. **Cleanup is label-scoped**: remove in `finally`, `terminate(batch)` with verification, reconciler cleanup for lost/overrunning/unconfirmed batches, and an age-based janitor sweep, all filtered by `sentinel.sandbox=1` plus the deployment scope.
8. **`JOB_EXECUTOR=stub` remains the default**; `docker` is an explicit operator opt-in.

## Consequences
- The worker host must be dedicated and treated as sensitive (docker group is root-equivalent; Q58).
- No dependency installation inside sandboxes yet (Q60); real test runners wait for Stage 9.
- A late worker no longer records results after the reconciler took its batch (ownership re-checked after each execution).
