# ADR-0006: Running a project's own tests and collecting results (Stage 9)

Status: Accepted (owner go-ahead for Stage 9 on 2026-10-24; decisions below were taken within that approval and are recorded for review). Resolves Q26, Q60, Q62, Q64; narrows Q59.

## Context
Stage 8 built the sandbox but ran only our own fixed script. Stage 9 must run a project's real tests (pytest) in it, normalize results, store cases and evidence, and let users watch, cancel and inspect runs, without weakening isolation, evidence integrity or cleanup.

## Decisions
1. **Offline, vendored pytest (Q60).** The sandbox keeps `--network none`. pytest and its pure-Python dependencies (pluggy, iniconfig, packaging, pygments) are copied into the image from the versions pinned in `backend/poetry.lock` by `sandbox/vendor.py` (refuses compiled extensions; writes `VERSIONS.json`). Project dependencies are not installed: a missing import is reported as an `error` with a plain explanation, never as a test failure. Allow-listed egress or a prebuilt wheelhouse is a later, separately reviewed design.
2. **Localhost/remote targets stay blocked (Q26).** Checks that need a URL are `blocked` before any container exists.
3. **`noexec` tmpfs kept (Q62).** Python imports and pytest fixtures work; tests that execute binaries from scratch space fail, and that is acceptable for now.
4. **Project code is an explicit operator opt-in (Q59).** `SANDBOX_ALLOW_PROJECT_CODE` defaults to false and requires `JOB_EXECUTOR=docker` plus either `SANDBOX_RUNTIME` (gVisor/Kata) or `SANDBOX_ACCEPT_SHARED_KERNEL=true` (written risk acceptance for plain runc). Disabled deployments return `blocked` and create no container. The catalog risk of `pytest_unit` is unchanged (low); the deployment gate, not plan risk, controls whether project code can run.
5. **Fixed command, validated parameters.** `pytest_unit` is `python -m pytest -p no:cacheprovider --junitxml=/tmp/junit.xml -o junit_family=xunit2 -q --color=no --tb=short [-- <target_path>]`. Only `target_path` (plain relative path, no `-`, `..`, spaces or shell characters) and `timeout_seconds` (10-3600, can only shorten the limit) vary; both were validated at plan time and are validated again.
6. **Result transport.** After the command ends (even on timeout) the trusted in-image runner reads the JUnit file (regular file only, `O_NOFOLLOW`, at most 2 MiB) and prints it as a nonce-framed, hash-checked base64 block at the end of stdout. The host keeps the tail of stdout in a ring buffer so output floods cannot cut the frame off, takes the last valid frame with its own nonce, and removes all frames from the stored log.
7. **Status comes from the exit state, never from the report.** pytest exit 0 `passed`, 1 `failed`, 5 `skipped` ("collected no tests"), anything else `error`; OOM `error`, timeout `timed_out`, cancel `cancelled`, container create/start failure `failed_to_start`. The JUnit file is written by the project's own code, so cases are only that code's account of itself: they are parsed defensively (size cap, no DOCTYPE/ENTITY, control characters stripped, text clipped, case count capped), redacted, stored, and labelled as the project's own report.
8. **One test timing out does not end the batch.** A per-test timeout is recorded and the batch continues; only batch/run cancellation or the batch time limit stops it.
9. **`not_run` is a real state (migration 0006).** Tests that never started (cancelled, timed out, lost worker, failed to start, batch cancelled while queued) get explicit `not_run` results with a reason. `test_case_results` stores individual cases (bounded column lengths) under the result that produced them.
10. **Evidence is served only through the project grant (Q64).** `GET /artifacts/{id}/content` serves run evidence (a log or report attached to a run), never uploads or scripts; authorizes from the artifact's own project (break-glass read-only and audited); re-checks the SHA-256; is always an attachment with `nosniff`, `no-store` and a sandboxing CSP; is audited. `GET /test-runs/{run}/results/{result}` returns the result with cases and evidence descriptors. The UI shows evidence as plain text only.

## Consequences
- Many real-world projects fail to import their dependencies and will report `error` until a dependency path exists (Q60, Q66).
- A project can lie about its own cases and can make its own tests pass; it cannot change another project's data, the platform, or the exit-state-derived status of a crash, timeout, OOM or cancel.
- Running project code under plain runc accepts shared-kernel risk (Q59); production should use a stronger runtime.
- The image must be rebuilt (`make sandbox-image`) to include pytest.
