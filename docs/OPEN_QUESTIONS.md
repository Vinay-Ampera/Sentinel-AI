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
| Q6 | Sandbox isolation level (Docker vs rootless/gVisor/Kata/VM) | No (Stage 8) | Threat-model first |
| Q7 | ~~First-release scope~~ **Resolved 2026-10-22** (see Stage 0 decisions below). Residual: repository providers beyond generic Git; localhost-URL access from a sandbox | No | Stage 2 design |
| Q8 | Celery+Redis cancel/retry/restart/duplicate behavior | No (Stage 7) | Proof of concept |
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
| Q26 | How a sandboxed worker reaches a developer's `localhost` target (tunnel/agent/project container) | Stage 8 | Decide with the sandbox threat model |
| Q27 | Admin scope/delegation model (default: no implicit global Admin access) and whether Developers may approve low/medium risk | Stage 4 | Owner to confirm matrix |
| Q28 | Real `sentinel-ai` database not inspected or migrated by Claude (credentials live in the denied `backend/.env`; none were requested). Re-confirmed 2026-10-22: migrations tested on a disposable DB only. **Owner reports (unverified by Claude) the migrations were applied to sentinel-ai with 28 tables (4 app_user, 24 public); effectively resolved** | Applying Stage 2 | Owner runs the inspection + `alembic upgrade head` commands in DATABASE_SCHEMA.md and reports `\dn`/`\dt` output |
| Q29 | Retention periods and artifact production store (proposals in DATABASE_SCHEMA) | Production | Confirm before production |
| Q30 | Super Admin bootstrap procedure (management command vs. one-time setup) | Stage 4 | Management command, password from prompt |

Q15–Q24 remain open; Stage 2 partially addressed: Q16 (tracker restructure not done), Q17 (state vocabularies reconciled in the schema: plan-item states follow the blueprint; run/batch states add `cancel_requested`/`timed_out`; `failed_to_start` is a result/planned-test status and a `dispatched→failed` transition), Q18 (categories fixed; capability matrix still to write), Q19 (retention proposed, tenant boundary = project/team), Q21 (matrix drafted).

## Stage 3 additions (2026-10-22)
| # | Question | Blocks | Handling |
|---|---|---|---|
| Q31 | ~~Redis required for readiness?~~ **Resolved 2026-10-22:** Redis stays reported but not required for readiness until Stage 7 (owner reports it is currently unavailable locally; the API is otherwise healthy). Revisit with the Celery proof of concept (Q8) | Closed | — |
| Q32 | Compose Redis/dev-PostgreSQL services are config-validated but not started; Redis unavailable locally | Stage 7 | **Deferred to Stage 7 by owner decision**; start with `docker compose up -d redis` then and record the result |
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

