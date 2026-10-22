# Open Questions and Uncertainties

Updated 2026-10-21. Resolve via ADR or tracker update.

## Resolved
- **Q1 Blueprint missing:** `docs/Sentinel_AI_Full_Project_Blueprint.md` now exists, byte-identical to `~/Downloads/Sentinel_AI_Full_Project_Blueprint_Updated.md`. Follow-up: ADR-0001 and architecture drafts are not yet cross-checked against it.
- **Q2 File naming:** `docs/IMPLEMENTATION_PLAN.md` is now the complete plan plus tracker; the duplicate `Sentinel_AI_IMPLEMENTATION_PLAN.md` and the redundant `Sentinel_AI_Project_Overview.md` were removed.
- **Q3 settings.json meanings:** root `settings.json` = product guardrails; `.claude/settings.json` = Claude Code permissions.
- **Q4 Execution path:** using `backend/src/sentinel_ai/execution/` (the tree path).

## Open
| # | Question | Blocks Stage 1? | Proposed handling |
|---|---|---|---|
| Q5 | Authentication/session mechanism and permission matrix | No (Stage 2/4) | Design in Stage 2 |
| Q6 | Sandbox isolation level (Docker vs rootless/gVisor/Kata/VM) | No (Stage 8) | Threat-model first |
| Q7 | First-release scope, supported app types, source input, repo providers | Stage 0 | Decide using the blueprint |
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
| Q14 | Blueprint §1/§15 say the stack is decided in planning before coding; ADR-0001 remains Proposed except the confirmed toolchain. | Owner to confirm rest of stack (FastAPI, Celery+Redis, LangGraph, Gemini, Docker isolation) before dependent stages |
| Q15 | Blueprint §13 lists `docs/ARCHITECTURE.md` as main overview; plan has only `docs/architecture/SYSTEM_ARCHITECTURE.md`. | Open: add `docs/ARCHITECTURE.md` (short index) or treat SYSTEM_ARCHITECTURE as it |
| Q16 | Blueprint §13/§15 want the tracker to track frontend, backend, shared integration, docs, deployment work separately with dependencies/tests; plan §16 does so only partially. | Open: restructure tracker per stage when Stage 2 starts |
| Q17 | State vocabularies differ: blueprint plan-item states (planned, approved, executed, skipped, blocked, failed-to-start, deferred), result categories (confirmed/likely/unverified/not reproduced/inconclusive), finding states (new…accepted risk), investigation labels (fact/likely/hypothesis/confirmed) vs plan run/result states (adds timed out, cancelled; lacks failed-to-start as distinct). | Open: reconcile in Stage 2 `DATABASE_SCHEMA.md` |
| Q18 | Blueprint §4 requires a capability matrix (applicability, prerequisites, permissions, integrations, limitations); not in plan or skeletons. Six application categories vs `settings.json` `supported_application_types` (empty). | Open: first-release categories (Q7) |
| Q19 | Tenant/team boundaries, retention rules, observability integrations, alert thresholds, evidence schema are undecided in blueprint §17 and unaddressed by skeletons beyond mentions. | Open: Stage 2 |
| Q20 | Blueprint §7 lists 11 logical agents; plan defines 5 graphs. Mapping not stated. | Open: Stage 11; AGENT_WORKFLOWS to document mapping |
| Q21 | Blueprint §6: Developers cannot approve actions reserved for Admin/Super Admin; no permission matrix yet (Q5). | Stage 2 |
| Q22 | Blueprint §12 success measures need baselines; TEST_STRATEGY has none. | Open: Stage 2/15 |
| Q23 | Test warning: `starlette.testclient` + `httpx` deprecation (suggests `httpx2`). | Upstream; revisit when pinning versions |
| Q24 | Backend `.venv` is created in-project (`backend/.venv`, git-ignored). | Fine; note in README if changed |
