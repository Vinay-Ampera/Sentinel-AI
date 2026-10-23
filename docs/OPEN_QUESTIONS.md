# Open Questions and Uncertainties

Updated 2026-10-22 (Stage 2). Resolve via ADR or tracker update.

## Resolved
- **Q1 Blueprint missing:** `docs/Sentinel_AI_Full_Project_Blueprint.md` now exists, byte-identical to `~/Downloads/Sentinel_AI_Full_Project_Blueprint_Updated.md`. Follow-up: ADR-0001 and architecture drafts are not yet cross-checked against it.
- **Q2 File naming:** `docs/IMPLEMENTATION_PLAN.md` is the plan (stage list, requirements, acceptance criteria) and `docs/PROJECT_TRACKER.md` holds detailed progress; the duplicate `Sentinel_AI_IMPLEMENTATION_PLAN.md` and the redundant `Sentinel_AI_Project_Overview.md` were removed.
- **Q3 settings.json meanings:** root `settings.json` = product guardrails; `.claude/settings.json` = Claude Code permissions.
- **Q4 Execution path:** using `backend/src/sentinel_ai/execution/` (the tree path).

## Open
| # | Question | Blocks Stage 1? | Proposed handling |
|---|---|---|---|
| Q5 | Authentication/session mechanism and permission matrix | No | **Implemented in Stage 4 on the owner's instruction to follow the documented design (ADR-0002 Accepted).** Original note: ADR-0002 (Argon2id + server-side sessions + CSRF; no SSO) and the matrix in SECURITY_AND_SAFETY. Confirm or amend before Stage 4 |
| Q6 | ~~Sandbox isolation level~~ **Resolved 2026-10-23 (Stage 8, ADR-0005):** hardened Docker (runc) is the baseline with a configurable runtime; production execution of genuinely untrusted project code needs gVisor/Kata or disposable VMs (Q59) | No | Closed |
| Q7 | ~~First-release scope~~ **Resolved 2026-10-22** (see Stage 0 decisions below). Residual: repository providers beyond generic Git; localhost-URL access from a sandbox | No | Stage 2 design |
| Q8 | ~~Celery+Redis cancel/retry/restart/duplicate behavior~~ **Resolved 2026-10-23 (Stage 7):** validated against a real Celery worker and Redis (publish/consume, SIGKILL recovery) plus DB-level tests for duplicate delivery, cancel, retry and timeouts; see ADR-0004 | No | Closed |
| Q9 | Migration tool, lint/type/test tools, pinned Python/Node versions (local: Python 3.12.3, Node 24.21.0; suggested: ruff, mypy, Alembic, Vitest) | **Yes** | Confirm before init |
| Q10 | Gemini model/budgets, artifact store, production topology, secrets management | No | Defer |
| Q11 | "Ponytail" tool is unidentified | No | Not recommended until clarified |
| Q12 | Directory is not a git repository | Soft | Ask before `git init` |
| Q13 | ADR-0001 and doc skeletons not yet reviewed against the blueprint | Stage 0 | Review blueprint, then confirm or amend ADR |

## Update: toolchain confirmed and blueprint review (2026-10-21)
- **Q9 resolved:** Python 3.12, Node 24, Ruff, mypy, Alembic, Vitest confirmed (ADR-0001 addendum). Vite template's oxlint kept for frontend lint; reversible.
- **Q12 resolved:** `git init -b main` run (no commits made).
- **Q13 resolved:** blueprint reviewed against ADR-0001 and skeletons. Findings:

| # | Finding | Handling |
|---|---|---|
| Q14 | **Resolved 2026-10-22:** FastAPI, Celery+Redis, LangGraph, Gemini, Docker confirmed (ADR-0001 now Accepted). Celery/Docker validation still pending (Q6, Q8). | No | Closed |
| Q15 | Blueprint §13 lists `docs/ARCHITECTURE.md` as main overview; plan has only `docs/architecture/SYSTEM_ARCHITECTURE.md`. | Open: add `docs/ARCHITECTURE.md` (short index) or treat SYSTEM_ARCHITECTURE as it |
| Q16 | Blueprint §13/§15 want the tracker to track frontend, backend, shared integration, docs, deployment work separately with dependencies/tests; plan §16 does so only partially. | Open: restructure tracker per stage when Stage 2 starts |
| Q17 | State vocabularies differ: blueprint plan-item states (planned, approved, executed, skipped, blocked, failed-to-start, deferred), result categories (confirmed/likely/unverified/not reproduced/inconclusive), finding states (new…accepted risk), investigation labels (fact/likely/hypothesis/confirmed) vs plan run/result states (adds timed out, cancelled; lacks failed-to-start as distinct). | Open: reconcile in Stage 2 `DATABASE_SCHEMA.md` |
| Q18 | Blueprint §4 requires a capability matrix (applicability, prerequisites, permissions, integrations, limitations); not in plan or skeletons. Six application categories vs `settings.json` `supported_application_types` (empty). | Categories decided (Q7): web apps, REST APIs, AI apps; capability matrix still to write in Stage 2 |
| Q19 | Tenant/team boundaries, retention rules, observability integrations, alert thresholds, evidence schema are undecided in blueprint §17 and unaddressed by skeletons beyond mentions. | Open: Stage 2 |
| Q20 | Blueprint §7 lists 11 logical agents; plan defines 5 graphs. Mapping not stated. | Open: Stage 11; AGENT_WORKFLOWS to document mapping |
| Q21 | Blueprint §6: Developers cannot approve actions reserved for Admin/Super Admin; no permission matrix yet (Q5). | Stage 2 |
| Q22 | Blueprint §12 success measures need baselines; TEST_STRATEGY has none. | Open: Stage 2/15 |
| Q23 | Test warning: `starlette.testclient` + `httpx` deprecation (suggests `httpx2`). | Upstream; revisit when pinning versions |
| Q24 | Backend `.venv` is created in-project (`backend/.venv`, git-ignored). | Fine; note in README if changed |

## Stage 0 decisions confirmed (2026-10-22, project owner)
- **Stack:** FastAPI, Celery + Redis, LangGraph, Gemini, Docker (ADR-0001 addendum).
- **Application types:** web apps, REST APIs, AI apps (RAG/agents).
- **Inputs:** Git repository, ZIP upload, localhost URL, live development/staging URL.
- **Testing modes:** automatic recommendations, prompt-based planning, developer-defined tests/scripts.
- **Excluded from initial release:** MiroFish.
- **Requirements:** evidence-backed findings; deterministic checks before LLM calls where practical with cost limits; extensible testing-tool integrations; restricted execution for project code and custom scripts; production testing blocked by default unless explicitly authorized and approved.
- **New follow-ups (Stage 2):** repository providers beyond generic Git; how a sandbox reaches a localhost URL; how live dev/staging URLs are authorized and scoped (must satisfy the production-blocked-by-default rule); sandboxing of developer-supplied scripts.

## Stage 2 additions (2026-10-22)
| # | Question | Blocks | Proposed handling |
|---|---|---|---|
| Q25 | Credentials for private Git repositories (deploy keys/tokens), providers beyond generic Git | Stage 6 | Secret-store design; no credentials in URLs (DB CHECK enforces) |
| Q26 | **Closed for Stage 9 (2026-10-24):** unchanged and confirmed (ADR-0006): URL/localhost-target checks stay `blocked`. **Decided 2026-10-23:** sandboxes have no network (`--network none`); checks needing a target URL are `blocked`. Reaching a localhost target (tunnel/agent/project container) and allow-listed egress are deferred to Stage 9 with the dependency story (Q60) | Stage 9 | Design with the first real runner |
| Q27 | Admin scope/delegation model (default: no implicit global Admin access) and whether Developers may approve low/medium risk | Stage 4 | Owner to confirm matrix |
| Q28 | Real `sentinel-ai` database not inspected or migrated by Claude (credentials live in the denied `backend/.env`; none were requested). Re-confirmed 2026-10-22: migrations tested on a disposable DB only. **Owner reports (unverified by Claude) the migrations were applied to sentinel-ai with 28 tables (4 app_user, 24 public); effectively resolved** | Applying Stage 2 | Owner runs the inspection + `alembic upgrade head` commands in DATABASE_SCHEMA.md and reports `\dn`/`\dt` output |
| Q29 | Retention periods and artifact production store (proposals in DATABASE_SCHEMA) | Production | Confirm before production |
| Q30 | Super Admin bootstrap procedure (management command vs. one-time setup) | Stage 4 | Management command, password from prompt |

Q15–Q24 remain open; Stage 2 partially addressed: Q16 (tracker restructure not done), Q17 (state vocabularies reconciled in the schema: plan-item states follow the blueprint; run/batch states add `cancel_requested`/`timed_out`; `failed_to_start` is a result/planned-test status and a `dispatched→failed` transition), Q18 (categories fixed; capability matrix still to write), Q19 (retention proposed, tenant boundary = project/team), Q21 (matrix drafted).

## Stage 3 additions (2026-10-22)
| # | Question | Blocks | Handling |
|---|---|---|---|
| Q31 | ~~Redis required for readiness?~~ **Resolved 2026-10-22:** Redis stays reported but not required for readiness until Stage 7 (owner reports it is currently unavailable locally; the API is otherwise healthy). Revisit with the Celery proof of concept (Q8) | Closed | — |
| Q32 | **Resolved 2026-10-23:** Compose Redis config reviewed (password required, 127.0.0.1 only, no persistence); tests used a separate throw-away Redis container, not your dev instance. Compose/dev-PostgreSQL services are config-validated; Redis unavailable locally | Stage 7 | **Deferred to Stage 7 by owner decision**; start with `docker compose up -d redis` then and record the result |
Resolved in Stage 3: Q9-era toolchain gap "baseline lint/format/type/test commands" (Makefile + README); Q24 unchanged. Q28: owner reports live migrations and health endpoints work against sentinel-ai (2026-10-22); recorded as owner-reported, not Claude-verified.

## Stage 4 additions (2026-10-22)
| # | Question | Blocks | Handling |
|---|---|---|---|
| Q33 | Password breach/common-password check is a small built-in list, not a breach corpus (e.g. a local HIBP k-anonymity list) | Production | Decide corpus before production |
| Q34 | `GET /users` is Admin/Super Admin only; API_DESIGN allows "limited" Developer visibility (members of shared teams/projects), deferred until projects/teams have routes. Admin scope is still "no implicit global access"; the delegation model for Admin approvals is a Stage 6 detail. Q27 (matrix confirmation) is treated as accepted by the Stage 4 instruction; policy-dependent matrix rows default to deny | Stage 5/6 | Implement with project/team routes |
| Q35 | Password reset tokens (`POST /admin/users/{id}/reset-password`, `password_reset_tokens` table) and team management routes not built; Admin-created users get an initial password supplied by the admin (no forced change yet). Q30 resolved: Super Admin bootstrap is `python -m sentinel_ai.cli create-super-admin` | Later | Build with the admin UI |

## Stage 5 additions (2026-10-22)
| # | Question | Blocks | Handling |
|---|---|---|---|
| Q36 | **Narrowed 2026-10-22:** Git / localhost / remote-URL sources are registered and validated (no network). Still open: *analysis* of them. Git needs a sandboxed clone (no hooks, depth/size limits, egress allow-list) and the credentials design (Q25); localhost needs Q26; remote URLs need an approved target authorization (Stage 6) and Stage 8 sandbox with DNS re-resolution at use time | Stage 6/8 | Implement with those stages |
| Q37 | Analysis is synchronous and returns 201 (API_DESIGN says 202 + polling). **Deferred to Stage 7** (job queue); the result schema will not change | Stage 7 | Move to a job |
| Q38 | **Resolved 2026-10-22:** keep the raw `application/zip` upload (streamed size cap, no extra dependency). Reopen only if the frontend needs multipart | Closed | - |
| Q39 | Temp-file half **resolved** (startup purge + `cli purge-temp`). Open: retention sweep for uploaded archives (proposal: 30 days after the last run) needs run history | Stage 7+ | Retention sweeper |

## Stage 6 additions and resolutions (2026-10-22)
| # | Question | Blocks | Handling |
|---|---|---|---|
| Q27 | **Resolved, revised in the access review:** approval is requested from explicit project members (designated approvers, else project managers), never the requester, with an organization role bound for high/critical; the global `developer_approval_risk_levels` delegation was removed. No role has implicit project access (Super Admin included). | Closed | ADR-0003 |
| Q34 | Partially resolved: `GET /approvals` gives Admin/delegated Developers a scoped inbox. `GET /users` for Developers is still not built | Later | Build with the admin UI |
| Q36 | **Narrowed again:** target authorization for remote dev/staging URLs is built (request, decide, revoke, gate). *Analysis* of Git / localhost / remote sources still needs the Stage 8 sandbox (clone, reachability, DNS re-resolution at use time) | Stage 8 | Implement with Stage 8 |
| Q40 | Prompt-based planning is deterministic keyword selection from the catalog. Free-text understanding (and LLM-assisted proposals) is Stage 11; it must keep producing catalog entries only | Stage 11 | Reuse `check_catalog` |
| Q41 | Authorization approvals are decided through `POST /approvals/{id}/decision` (API_DESIGN no longer lists a separate `/authorizations/{aid}/decision`). Confirm | No | Owner to confirm |
| Q42 | Localhost URL sources need no authorization (loopback-only by validation and DB CHECK). Whether a sandbox can reach them is Q26 | Stage 8 | Decide with the threat model |
| Q43 | Authorization window caps (30 days; production 24 h), `allowed_risk` limited to low/medium/high, plan size (60), parameters (5) and plan-creation rate limit (30/min per user, in process) are constants in code. Confirm or make configurable | No | Owner to confirm |
| Q44 | Plan-level approval only (one approval per submitted plan at its highest risk). Per-test approvals (column exists) are unused. Withdraw = the requester rejecting their own pending plan; there is no "revise a submitted plan" - create a new version | No | Owner to confirm |
| Q45 | Production remote sources cannot be registered (Stage 5), so production authorization is unreachable through the API; the policy/Super Admin path is implemented and tested against a database-inserted source. Decide whether/when to allow registering production sources at all | Later | Owner decision |
| Q46 | Frontend has sign-in, project/plan list, plan review/submit/approve/reject, but no router, project/source creation, upload, analysis, authorization or policy screens; verified by unit tests only (no browser/axe run) | Stage 9+ | Grow UI with later stages |

## Access review decisions - resolved by the owner (2026-10-23)
| # | Decision | Implementation |
|---|---|---|
| Q47 | **Resolved:** temporary, time-limited, fully audited Super Admin break-glass access. | `POST /projects/{id}/break-glass` (Super Admin; justification ≥ 20 chars; 5-240 minutes, DB cap 4 h; READ-only; one active grant per project and user; no extension, no edits). Revocable at once by the grantee or a project manager; managers can list grants. Expiry by the database clock; only while the user is still a Super Admin. Audit: `breakglass.grant`, `breakglass.access` (every request served only because of it), `breakglass.revoke`. Migration 0004 (new table `break_glass_grants`). Break-glass projects are not added to `GET /projects`. |
| Q48 | **Resolved:** Super Admin needs explicit project access before approving production. | Decisions use `resolve_explicit_access`; break-glass never counts (403 "read-only"), and a designation does not either. Any explicit grant (read is enough) qualifies. |
| Q49 | **Resolved:** Developers cannot approve high/critical risk by default. | The organization key `high_risk_approver_roles` (Super Admin only) may add `developer`; default `["admin","super_admin"]`. Projects cannot set it. Even when opted in, a Developer still needs a project grant (manager or designated) and cannot approve their own request. Empty or unknown values fall back to Super Admin only. |
| Q50 | **Resolved:** no self-approval; a different authorized person approves. | Enforced at every risk level and role (policy code); the requester may only withdraw (reject). DB CHECK also blocks self-approval for high/critical. |
| Q51 | **Resolved:** project managers manage project risk policy within organization limits. | `PUT /projects/{id}/policies/{key}` needs `manage`; allowed levels intersect with the organization's, approval levels only add, production can never be enabled by a project. Unused role permissions `approval.low_medium` and `policy.project_scope` removed. |

Residual notes: break-glass has no organization kill switch yet and no notification to project managers beyond the audit log and the grant list (candidate for Stage 12 alerts).

## Stage 7 additions (2026-10-23)
| # | Question | Blocks | Handling |
|---|---|---|---|
| Q52 | Q37 **deferred again**: project analysis stays synchronous (201). Moving it to a job changes the Stage 5 contract and needs worker-side source handling that overlaps the Stage 8 sandbox boundary | Stage 8+ | Revisit with Git/remote analysis |
| Q53 | `POST /test-runs/{id}/rerun` (API_DESIGN) not built: Stage 7 scope was create/status/cancel/progress. A rerun today is a new `POST /projects/{id}/test-runs` of the same approved plan (allowed once the previous run is terminal). `parent_run_id`/destructive re-approval semantics are open | Stage 9/15 | Owner to confirm |
| Q54 | Any project member with `run` access can cancel any run of the project (not only the starter). The worker's revalidation uses the **starter's** current access, so removing the starter stops their queued runs | No | Owner to confirm |
| Q55 | Termination of a sandbox whose worker was lost cannot be confirmed by the reconciler; the batch is recorded as `cancelled` with `worker_lost_during_cancel` / `termination_confirmed: false`. **Resolved 2026-10-23 (Stage 8):** the reconciler now calls `terminate` (removal by label, verified) for lost, overrunning and unconfirmed-cancel batches and records `sandbox_cleanup_confirmed`; with the stub executor nothing is confirmed, as before | Closed | — |
| Q56 | Defaults chosen with the owner (batch 10, 2 per run, 4 global, lease 60 s, grace 30 s, 1 attempt, timeouts 1800/3600/3600 s) are environment-tunable `JOB_*` settings, not per-project policy. `.env.example` was not updated (outside permitted paths) | No | Owner adds the variables if wanted |
| Q57 | One intermittent failure of `test_analysis_result_separates_facts_inferences_and_gaps_and_is_persisted` appeared in a full run (also seen once in Stage 6); it passes alone and in repeated runs. It reads `analyses` `items[0]`, which is probably an ordering tie. Not Stage 7 code; not investigated | No | Look at analysis list ordering |
Also: `celery[redis]` pulled `kombu 5.7.0rc1` (needed redis 8); pinned `kombu >=5.6,<5.7`, which lowered `redis` to 6.4.0. Revisit when kombu 5.7 is stable.

## Stage 8 additions (2026-10-23)
| # | Question | Blocks | Handling |
|---|---|---|---|
| Q58 | The worker talks to Docker, and membership of the `docker` group is root-equivalent on the host. A bug that lets an attacker influence Docker arguments would compromise the host. Mitigated by fixed argv, validated settings and an empty CLI environment; not eliminated | Production | Run workers on a dedicated host/VM; evaluate rootless Docker or a socket proxy |
| Q59 | **Gated in Stage 9 (2026-10-24, ADR-0006):** project code is off by default and needs `SANDBOX_ALLOW_PROJECT_CODE` plus a stronger runtime or `SANDBOX_ACCEPT_SHARED_KERNEL=true`; gVisor/Kata themselves are still untested. Original: Shared-kernel isolation: runc is the baseline. Stage 8 runs only our own fixed script on the extracted tree, never project code. Stages that run project code (pytest, npm, custom scripts) need gVisor/Kata or disposable VMs in production, or an explicit risk acceptance. `SANDBOX_RUNTIME` is validated and passed to Docker but was not tested with a real alternative runtime (none installed) | Stage 9+ production | Install and test `runsc`/Kata before enabling project-code runners |
| Q60 | **Decided 2026-10-24 (ADR-0006):** Stage 9 stays offline with a vendored pytest stack; dependencies are not installed and missing imports are reported as `error` (follow-up Q66). Original: No network means no dependency installation and no remote or localhost targets. Stage 9 needs allow-listed egress and/or a prebuilt-dependency path, plus a decision on reaching localhost targets (Q26) | Stage 9 | Design with the pytest runner |
| Q61 | The runner image is built locally from `python:3.12-slim` (no pull); it is not pinned by digest or scanned. The image ID is recorded in every manifest | Production | Pin by digest, rebuild and scan regularly |
| Q62 | **Kept `noexec` (2026-10-24):** pytest works; tests that execute binaries from scratch space fail. Original: Sandbox tmpfs is `noexec`; Stage 9 runners may need an executable scratch area | Stage 9 | Justify and relax narrowly if needed |
| Q63 | No host-wide CPU/memory accounting across workers; concurrency is bounded only by Celery concurrency and `JOB_MAX_CONCURRENT_BATCHES` | Production | Capacity limits with deployment (Stage 16) |
| Q64 | **Resolved 2026-10-24 (Stage 9):** JUnit XML is collected, cases are stored, and `GET /artifacts/{id}/content` serves run evidence through the project grant (retention is Q70; coverage/other files are not collected). Original: Evidence (stdout, stderr, manifest) is stored and listed in `artifacts` but there is no download endpoint, authorization or retention yet; result files (JUnit XML, coverage) are not collected | Stage 9 | Build artifact download/authorization and file collection with result inspection |
Also: `SANDBOX_*` limits are environment settings, not per-project policy; `.env.example` was not updated (outside permitted paths); no Stage 8 migration; `sandbox_smoke` is developer-selectable only (not in automatic or prompt plans).

## Stage 9 additions (2026-10-24)
| # | Question | Blocks | Handling |
|---|---|---|---|
| Q65 | The owner went straight to implementation for Stage 9 (no design pause). The decisions in ADR-0006 (offline vendored pytest, project-code opt-in flags, `not_run` state, exit-code-derived status, evidence download rules) were taken within that approval | No | Owner to confirm or amend ADR-0006 on review |
| Q66 | Projects that import third-party packages cannot be tested yet (offline sandbox, stdlib + pytest only); they report `error` with an explanation. A dependency path (reviewed allow-listed egress, or a prebuilt per-project wheelhouse/image) needs its own design and threat-model update | Stage 10+ | Design before enabling more runners |
| Q67 | A project's JUnit report is written by its own code: cases (and their messages) are only that code's account of itself. The result **status** comes from the exit state, but a project can still make its own tests pass or fake its own cases. Documented in the UI ("reported by the project's own test report") and the threat model | No | Accepted; revisit with stronger verification in Stage 15 |
| Q68 | The runs UI (start, progress polling, cancel, results, cases, evidence view) is verified by unit tests only (Vitest/jsdom): no browser run, no axe accessibility check, no live API session | Stage 12+ | Add browser/axe checks with the frontend test plan |
| Q69 | Playwright/browser execution was **not** started: it needs a browser-capable sandbox image, larger limits and a reviewed network story for targets (Q26/Q60) | Stage 10+ | Separate increment after browser sandboxing is validated |
| Q70 | No retention sweeper for evidence, cases or uploaded archives yet (Q39 still open); evidence has no size quota per project | Production | Retention job with deployment (Stage 16) |
| Q71 | Only Python (`pytest_unit`) has a runner. `js_unit` and the others remain `skipped` ("no sandbox runner"). The vendored pytest versions are in `sandbox/vendor/VERSIONS.json` (git-ignored, regenerated per build) but are not yet recorded in each manifest | No | Record runner versions in manifests when adding runners |
| Q72 | `POST /test-runs/{id}/rerun` is still unbuilt (Q53); re-running means starting a new run of the same approved plan once the previous one is terminal | No | Owner to confirm |
| Q73 | **Semgrep: VERIFIED 2026-10-23 (ADR-0008 update).** semgrep 1.182.1 in `sentinel-scanner-runner:stage10`; fixed command ran offline; all 16 bundled rules fired on a vulnerable sample. Remaining: only Python and JS/TS rules exist (Q81); `semgrep --validate` needs the network so it is not part of an offline check | Stage 10 follow-up | Done; broaden rules under Q81 |
| Q74 | **Dependency audit: VERIFIED with real OSV data 2026-10-23.** Offline audit against the baked-in bundle (PyPI 31,031 / npm 232,804 advisories); host refuses data older than 30 days (image label). Not covered: yarn/pnpm/Cargo/etc. lockfiles, unpinned or lockfile-absent packages, reachability. Refresh is manual (`make advisories` + rebuild; Q82) | Stage 10 follow-up | Schedule refreshes; licence review (Q82) |
| Q75 | **OWASP ZAP: container mechanics VERIFIED in a lab, still DISABLED (ADR-0008 update).** ZAP 2.17.0 baseline ran under the full sandbox hardening on an `--internal` network against a local target; report framed and parsed (15 alerts). Not verified: the host-firewall restriction (root needed), public-target resolution/pinning with the real executor flow, `zap_active`. Do not set `SANDBOX_ZAP_EGRESS_ATTESTED` until the firewall rules in the threat-model checklist exist and were tested | Stage 10 follow-up | Owner: provision and test the firewalled network, then one baseline run against an authorized dev/staging target |
| Q76 | Bandit severity/confidence are the tool's own and Bandit is a heuristic matcher (false positives and negatives). Severity is not adjusted by Sentinel, and `critical` is never produced. Whether to add a Sentinel risk score, or suppress known-noisy rules (for example B101 assert, B404 import subprocess), is undecided | No | Owner to decide with real findings in hand |
| Q77 | Finding API surface from `API_DESIGN.md` that was not built: `PATCH /findings/{id}` (assignment), manual `POST /findings/{id}/evidence`, regression-test proposal endpoints, `POST /findings/{id}/verify-fix`. Status and verification have their own POST endpoints | Stage 11-12 | Build with the workflows that need them |
| Q78 | Re-scan verification is per source: a re-uploaded archive is a new `project_sources` row, so findings of the old source are not auto-verified by a scan of the new one (and a finding seen again moves to the newest source). Also an unchanged fingerprint depends on message and occurrence order, so inserting an earlier identical issue can renumber later ones | No | Decide whether sources get versions (Q25) |
| Q79 | **Resolved 2026-10-23 (ADR-0008):** findings are linked across tools and advisories by `finding_groups` (never merged; location groups need two tools, same file + CWE, lines within 3; advisory groups share an alias). Remaining gap: no grouping by rule/file in the UI list, and ZAP findings are not grouped with static ones | Stage 10 follow-up | Revisit with real multi-scanner data |
| Q80 | The findings UI is verified by unit tests only (Vitest/jsdom): no browser run, no axe check, no live API session. Also no retention policy for findings evidence (Q70) | Stage 12+ | With the frontend browser/axe plan (Q68) |
Also: `make sandbox-image` now needs the backend virtualenv (pytest is copied from it, pure-Python only, no network); the `sandbox/vendor/` directory is git-ignored. A single test hitting its own timeout no longer ends its batch (worker change). `sandbox_smoke` is unchanged.

Stage 10 note: `make sandbox-image` now also vendors Bandit and its pure-Python dependencies (PyYAML without its C accelerator); `bandit` is a backend dev dependency in `poetry.lock`. Migration 0007 adds the finding columns (not applied to the real DB).
| Q81 | Semgrep rule coverage is a small, hand-written starter set (16 rules; Python and JS/TS only). Whether to adopt a larger reviewed rule pack (and its licence, since the Semgrep registry rules have their own terms) is undecided | No | Owner to choose; add only rules that pass `semgrep --validate` |
| Q82 | The advisory feeds (OSV: GitHub Advisory Database, PyPA) have licence/attribution terms that apply to an image that bakes them in; not reviewed. Also no automatic refresh: nothing rebuilds the image when the 30-day limit nears | Production | Review licences; add a scheduled advisory refresh + image rebuild (Stage 16) |
| Q83 | The ZAP egress restriction is an operator-owned host firewall rule that Sentinel can only take on trust (`SANDBOX_ZAP_EGRESS_ATTESTED`). A misattested network is undetectable from the application. Alternatives (a per-run proxy sidecar enforcing a host allow-list, a network namespace helper) were not built | Production | Decide whether to build a Sentinel-managed egress proxy before enabling ZAP beyond a lab |
| Q84 | Dependency audit coverage: yarn.lock, pnpm-lock.yaml, Cargo.lock, go.sum, Gemfile.lock, composer.lock are detected but not audited (the scan is reported incomplete); version matching for npm is a small SemVer comparator, not the full npm range grammar (OSV events are exact versions, so this should be sufficient, but only fixtures were tested). No reachability analysis | No | Add parsers per ecosystem on demand |
| Q85 | ZAP baseline/active take fixed spider/total minutes (1/8 and 2/20) and only a URL path as parameters; authenticated scans, API-spec (OpenAPI) scans, ajax spider and context files are not supported | No | Design with the authenticated-testing story |
| Q86 | Dynamic (ZAP) findings never auto-verify as fixed and are not linked to the code that serves the URL; the `finding_groups.kind` check allows only `location` and `advisory` | No | Revisit once there is a way to map routes to source |

## Frontend track (F0, 2026-10-23)
| # | Question | Blocks | Proposed handling |
|---|---|---|---|
| Q87 | The test-execution-report screenshot named as the layout reference for report pages (F5) could not be found on this machine (searched ~/Pictures/Screenshots, ~/Downloads; recent screenshots are a marketing page, chat/IDE captures and the API docs page). **Resolved 2026-10-23: the owner told Claude to build F5 from ui-ux-design.md; the screenshot was never used.** | F5 | Ask the owner for the file before F5; until then follow the "QA dashboard and reports" notes in ui-ux-design.md. |
| Q88 | `index.html` has a small inline script that applies the saved theme before first paint. A strict Content-Security-Policy that forbids inline scripts would need a nonce/hash for it. No CSP is set today. | F16/deployment | Decide with the Stage 16 deployment headers; the script is 12 lines and mirrors `src/theme/theme.js`. |
| Q89 | Automated axe checks run in jsdom, which has no layout, so colour contrast is verified separately from the real token file, and keyboard order, focus visibility, zoom/reflow and screen-reader behaviour are not machine-checked. | F9 | Manual keyboard and screen-reader pass recorded in F9; no conformance claim until evaluated. |
| Q90 | F0 was not viewed in a real browser (no browser session was available to Claude): layout, the mobile menu and theme appearance are unverified visually. | F0 review | Owner to look at `npm run dev` in light/dark/system and a narrow window; findings feed F1. |
| Q91 | Adding a project member needs to find the person, but `GET /users` (the only lookup) is limited to administrators, and `PUT /projects/{id}/members/{user_id}` needs a user id. A developer with manage access can list and change members but cannot add one in the UI; the dialog says so. | F3 | Backend decision: allow members-manage to look up users by exact email, or add an invite-by-email route. Not changed (no backend work in the frontend track). |
| Q92 | An approval row has only `project_id`, so the Approvals page lists projects (including archived) to show names. Plans must be reviewed on their own page to decide; only target-authorization approvals are decided directly in the list. | F4 | Fine for now; a project name in the approval payload would remove the extra call. |
| Q93 | Runs and findings are shown with their existing panels as project tabs (labelled as the existing view) until F5/F6. F5 is blocked on Q87. | F5/F6 | Resolved: F5 and F6 rebuilt both views. |
| Q94 | The project and organization policy editors change only the risk-level lists (and, for the organization, approver roles and the production-testing flag). Per-level designated approvers (`risk_approvers`) are shown, not editable, in the UI. | F7 | Add an approver picker later if wanted; the API supports it. |
| Q95 | A policy key that has never been saved shows as empty in the organization editor (the server's built-in default applies, and the API does not return it). | F7 | Backend could return the defaults with the stored rows. |
| Q96 | Break-glass grants carry only a user id, so the page cannot show who holds emergency access by name. | F7 | Backend could include the grantee's display name. |
| Q97 | **Resolved 2026-10-23:** F5 was built from ui-ux-design.md (no screenshot). The layout may differ from the owner's reference; adjust after review. | F5 | Owner review. |
| Q98 | `GET /projects/{id}/test-runs` returns runs without progress or result counts, so the run history shows status, plan and duration only; counts appear on each run's report. | F5 | A server-side summary on the list (or a counts field) would let the history show pass/fail counts. |
| Q99 | The report refreshes by polling every 3 seconds while a run is active (skipped while the tab is hidden) and reloads the whole event list each time; the events endpoint's `after` cursor and the list endpoint's `limit` (default 50) are not used by the client. | F5 | Fine for current run sizes; use the cursor or a push channel if runs get long. |
| Q100 | Not in F5 because the API does not provide it: coverage figures, run-to-run comparison (Stage 15), report export or print, and a per-check live log. Logs and reports are reachable only as stored evidence. | F5 | Revisit with Stages 14-15. |

