# ADR-0001: Initial Technology Stack

- **Status:** Accepted 2026-10-22 (stack and first-release scope confirmed by the project owner; see addendum)
- **Date:** 2026-10-21

## Context
The plan (`docs/IMPLEMENTATION_PLAN.md` §2) recommends a starting stack. The blueprint was not available when this was recorded and has not yet been cross-checked against these choices.

## Decision (initial)
| Area | Choice |
|---|---|
| Frontend | React + Vite + JavaScript (JSX), React Router, CSS variables |
| Backend | Python + FastAPI, Poetry |
| Orchestration | LangGraph; Gemini API behind a provider boundary |
| Database | PostgreSQL (vector search deferred; pgvector only if needed) |
| Jobs | Celery + Redis; job history in PostgreSQL |
| Isolation | Hardened Docker execution containers |
| QA / security / a11y | pytest, Playwright; Semgrep, Bandit, OWASP ZAP; axe-core |
| Telemetry | OpenTelemetry |
| Artifacts | Local dir behind an interface (dev); production store TBD |
| API | Versioned REST `/api/v1`, FastAPI OpenAPI |
| Dev / CI | Docker Compose; GitHub Actions |
| Schema | Versioned migrations (tool TBD) |

## Consequences
- Avoid Kubernetes, vector DB, multiple model providers until justified.
- Celery+Redis and Docker isolation must be validated by proof of concept / threat model before reliance.
- Stack is a starting decision, not evidence anything is installed or working.

## Alternatives not evaluated
Recorded only as future change candidates: rootless Docker/gVisor/Kata for isolation; alternative queues. Changes require a new ADR.

## Addendum 2026-10-21 — confirmed toolchain
Confirmed by the project owner: Python 3.12, Node.js 24, Ruff, mypy, Alembic, Vitest. These are accepted. The rest of the table remains Proposed.
Blueprint §1 and §15 say the stack is to be agreed in implementation planning before coding; this confirmation covers only the items above, so confirm the remaining choices (see OPEN_QUESTIONS Q14) before the stages that depend on them.
Stage 1 additionally used (Vite template defaults, not separately decided): oxlint for frontend lint, `@testing-library/react` + jsdom for component tests.

## Addendum 2026-10-21 — frontend uses JavaScript, not TypeScript
Owner decision: the frontend is plain JavaScript (React + Vite, JSX). This supersedes "TypeScript" in the table above and in the implementation plan. Trade-off: no compile-time type checking; rely on tests, oxlint, and runtime validation of API responses at the service layer. Frontend `build` is now `vite build` (no `tsc`). Reversible later by adding TypeScript.

## Addendum 2026-10-22 — Stage 0 decisions confirmed (owner)
**Stack confirmed:** FastAPI, Celery + Redis, LangGraph, Gemini (behind a provider boundary), Docker (hardened execution containers). The rest of the table above is accepted as written (JavaScript frontend per the earlier addendum). Celery+Redis behavior (Q8) and Docker isolation level (Q6) still need a proof of concept / threat model before dependent stages rely on them; confirming the choice does not mean they are validated.

**First-release application types:** web apps, REST APIs, and AI apps (RAG/agents).

**Inputs:** Git repository, ZIP upload, localhost URL, live development/staging URL. Repository providers beyond generic Git, and how localhost URLs are reached from a sandbox, are Stage 2 design items.

**Testing modes:** automatic recommendations, prompt-based planning, and developer-defined tests/scripts.

**Excluded from the initial release:** MiroFish.

**Requirements recorded**
- Findings must be evidence-backed; no result or vulnerability is claimed without recorded evidence.
- Deterministic checks run before LLM calls where practical; LLM use is subject to cost/token limits (budgets defined in Stage 2).
- Testing-tool integrations are extensible (adapter/provider boundary, not hard-wired).
- Project code and developer-supplied custom scripts run only in restricted sandboxes.
- Production testing is blocked by default; it requires explicit authorization, a documented scope, and approval.
