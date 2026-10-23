# Sandbox Threat Model (Stage 8)

> Status: **implemented and tested in Stage 8** (ADR-0005). Scope: the Docker sandbox that executes fixed catalog commands for approved runs. Read with `JOB_AND_SANDBOX_DESIGN.md`, `SECURITY_AND_SAFETY.md`.

## What is protected, from whom
**Assets:** the host and its other containers, platform secrets (DB, Redis, session pepper, API keys), the artifact store and other projects' data, the Docker daemon, and result integrity.
**Trusted:** the API, the worker, PostgreSQL, Redis, the Docker daemon, the fixed runner script in the image (`sandbox/entry.py`, `smoke.py`).
**Untrusted:** uploaded ZIP bytes and names, any code inside them, everything a sandbox prints, every file it creates, and its timing.
**Attacker goals:** escape to the host, read secrets or other projects, reach the network (SSRF, exfiltration), exhaust resources, forge results, persist after cancel/timeout, or poison logs.

## Threats and controls
| # | Threat | Control (enforced in code) | Test |
|---|---|---|---|
| T1 | A compromised worker controls Docker (the `docker` group is root-equivalent) | The worker never runs untrusted code. `DockerRunner` runs fixed argv vectors (no shell); container names are generated, labels are UUIDs/validated values, the image/runtime/scope are regex-validated in settings and again in `SandboxSpec.validate`. No request field reaches a Docker flag. The CLI gets a minimal environment (no worker secrets). **Residual risk, see below.** | `test_sandbox.py` (argv, validation) |
| T2 | Container escape (kernel/runc bug) | No `--privileged`, devices, host mounts or Docker socket; `--cap-drop ALL`; `no-new-privileges`; default seccomp and AppArmor; read-only rootfs; non-root numeric user `65534:65534`; `--ipc none`; own PID/mount/UTS namespaces; `--init`. `SANDBOX_RUNTIME` selects a stronger runtime (gVisor `runsc`, Kata) without code changes. | `test_sandbox_docker.py` (identity/caps, configuration as the daemon sees it, filesystem) |
| T3 | Reading platform secrets or host files | Empty container environment (fixed `PATH/HOME/LANG` only); no bind mounts or volumes; the source ZIP is streamed over stdin, never mounted; `/workspace` and `/tmp` are fresh per-container tmpfs. | env, mounts and host-path tests |
| T4 | Network use (SSRF, exfiltration, cloud metadata, host loopback) | `--network none`, unconditionally; no setting enables it. Only `lo` exists in the container. Checks that need a network target return `blocked` before any container exists. | network test (loopback host port, bridge gateway, internet, metadata, DNS, interfaces) |
| T5 | Resource exhaustion | `--cpus`, `--memory` with `--memory-swap` equal (no swap), `--pids-limit`, `nofile`, `fsize`, `core=0` ulimits, size-capped tmpfs (which count against memory), output cap in the host reader (surplus is drained and discarded), timeout in the runner **and** a host deadline (timeout + 5 s) that kills a container whose runner was frozen. `nproc` is deliberately not used (it is per-uid host-wide, not per container). | memory, pids, disk, flood, timeout, frozen-runner tests |
| T6 | Malicious ZIP (traversal, absolute, symlink/device, duplicate, bomb, huge count) | Header validation again on the host (`archive.inspect_archive`, nothing extracted on the host). Extraction happens only inside the sandbox: strict name checks, no special files, `O_EXCL|O_NOFOLLOW`, real byte counts (not header claims), file/total/count caps, `0600` files. | extractor unit tests, six hostile-archive container tests |
| T7 | Another project's workspace or tampered upload | The worker resolves the source only from the run's own project (`projects.list_sources(project_id)` and `get_artifact(project_id, ...)`), the executor re-reads the bytes once, checks SHA-256 against the recorded value, and sends exactly those bytes. Storage keys are validated against the store root. | workspace-scope, hash-mismatch tests |
| T8 | Forged or poisoned output | The host takes status only from `docker inspect` (exit code, `OOMKilled`) and its own timers, never from output. Output is decoded safely, stripped of control/ANSI sequences, redacted of configured secrets and credential shapes, capped, and stored under fixed names with SHA-256. | forge, redaction, evidence e2e tests |
| T9 | Containers outliving a cancel, timeout or lost worker | `always rm -f -v` in `finally`; `terminate(batch)` removes by label and verifies; the reconciler calls it for lost, overrunning and unconfirmed-cancel batches; a janitor sweep removes this scope's labelled containers past `test timeout + grace + 120 s`; the runner has its own timeout. All cleanup filters on `sentinel.sandbox=1` **and** the deployment scope label, so other containers are never touched. | cancel, cleanup, janitor, reconciler e2e tests |
| T10 | Unauthorized or risky targets | Stage 7 revalidation is unchanged. Only commands from the fixed table run; unknown checks are `skipped`; network checks `blocked`. `JOB_EXECUTOR=stub` is the default; `docker` is an operator opt-in. | unit and e2e tests |

## Residual risks (accepted for Stage 8, tracked in OPEN_QUESTIONS)
1. **Docker group = root on the worker host (Q58).** A bug in worker code that lets an attacker influence Docker arguments would be host compromise. Mitigated by fixed argv and validation, not eliminated. Run workers on a dedicated host/VM; prefer rootless Docker or a socket proxy later.
2. **Shared-kernel isolation (Q59).** Hardened runc is the baseline. Stage 8 executes only our own fixed script on the extracted tree, never project code. **Before any stage runs genuinely untrusted project code (pytest, npm, custom scripts) in production, use gVisor/Kata or disposable VMs** (`SANDBOX_RUNTIME`), or accept the shared-kernel risk explicitly.
3. **No egress, therefore no dependency installation (Q60).** Stage 9 must design allow-listed egress or a prebuilt-dependency path; localhost-target reach (Q26) is deferred with it.
4. **Image supply chain (Q61).** The runner image is built locally from `python:3.12-slim` without pulling; pin it by digest and rebuild regularly. The image ID is recorded in each manifest.
5. **tmpfs is `noexec` (Q62).** Fine for Stage 8; Stage 9 runners may need an executable scratch area, to be justified then.
6. **Host-wide capacity (Q63).** Concurrency is bounded by Celery concurrency and `JOB_MAX_CONCURRENT_BATCHES`; there is no host-wide CPU/memory accounting across workers.
7. **Evidence is stored but not yet downloadable (Q64).** Artifact download/authorization/retention arrives with Stage 9 (result inspection).

## Operating notes
- Build once: `make -C backend sandbox-image` (tag `sentinel-sandbox-runner:stage8`). Enable with `JOB_EXECUTOR=docker`; leave `SANDBOX_SCOPE` per deployment (tests use unique scopes).
- Never run the worker as root, never add the worker to a shared host's docker group, never mount the Docker socket into anything the worker starts.
- Verify after changes: `poetry run pytest tests/integration/test_sandbox_docker.py` (needs Docker and the image).
