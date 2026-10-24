# System Architecture

> Status: **Stage 2 — finalized design** (ADR-0001 Accepted, ADR-0002 Proposed for auth). Nothing here is implemented beyond the database migrations. Blueprint cross-check: see OPEN_QUESTIONS Q13–Q24.

## First-release scope (ADR-0001 addendum)
Application types: web apps, REST APIs, AI apps (RAG/agents). Inputs: Git repository, ZIP upload, localhost URL, authorized development/staging URL. Testing modes: automatic recommendations, prompt-based planning, developer-defined tests/scripts. Excluded: MiroFish.

## Components
1. **React frontend** (JavaScript) — projects, plan review, progress, findings, history. UX-only role checks.
2. **FastAPI backend** — `/api/v1`; authn (server-side sessions), authz, project/plan/run/evidence APIs. Layers: `api → services → repositories → models`.
3. **PostgreSQL** (`sentinel-ai`): schema `app_user` (identity/sessions) and `public` (application). Durable source of truth for state, approvals, audit.
4. **Redis** — Celery broker only; never the source of truth.
5. **Celery workers** — claim jobs, **revalidate authorization and policy**, drive the batch lifecycle, update PostgreSQL.
6. **Sandbox executor** — restricted Docker containers for target code, custom scripts, and testing tools (JOB_AND_SANDBOX_DESIGN).
7. **LangGraph orchestration** — conditional reasoning (analysis, planning, investigation, verification); never executes commands itself.
8. **Gemini provider service** — one boundary for all LLM calls: timeouts, token/cost limits from `policies`, usage rows in `llm_usage`, redaction before send.
9. **Tool-integration layer** — adapters behind a common interface (below).
10. **Artifact store** — interface; local directory in development, production store TBD (Q10).
11. **Telemetry** — OpenTelemetry-compatible correlation (Stage 13; Stage 12 ingests structured events and stores trace ids only as opaque references, ADR-0011).

## Trust zones
| Zone | Contents | Trust |
|---|---|---|
| Browser | Frontend | Untrusted client |
| Platform | API, workers, Postgres, Redis | Trusted; holds secrets |
| Sandbox | Target code, custom scripts, test tools | Untrusted; no platform secrets, no Docker socket, network denied by default |
| External | Gemini API; scan targets (dev/staging URLs) | Separate; targets require authorization |

Repository files, ZIP contents, logs, prompts, and tool output are untrusted data everywhere, including inside LLM prompts.

## Input handling
| Source | Handling |
|---|---|
| Git repository | Cloned by a worker into a disposable workspace (no credentials in the URL; provider tokens, if ever needed, come from the secret store — Q25). Pinned to a commit SHA recorded in `analysis_snapshots`. |
| ZIP upload | Stored as an `upload` artifact (size cap, content-type check, hash). Extracted only in a worker/sandbox after validation (path traversal, symlinks, zip bombs, file-count/size limits); `validation_status` tracks it. |
| Localhost URL | Host restricted by DB CHECK to localhost/127.0.0.1/[::1]. The sandbox cannot reach the developer's localhost by default; how it is exposed (e.g., a developer-run agent/tunnel or a project container) is an open design item (Q26). |
| Dev/staging URL | `remote_url` source + an **approved, time-boxed `target_authorizations` row** scoping hosts/paths/risk levels. Production environment is blocked unless the global policy allows it **and** an approved four-eyes authorization exists. |

## Testing modes
- **Automatic recommendations:** deterministic analysis (stack detection, OpenAPI/route discovery, dependency/manifest inspection) proposes `planned_tests` with `origin = recommended`; an LLM is called only to add reasoning where deterministic output is insufficient.
- **Prompt-based planning:** user prompt stored on the plan (`plan_mode = prompt_based`); the planner maps it to known tool adapters; output is validated against the same risk/approval policy as any plan. A prompt can never add a tool that is not registered or widen scope.
- **Developer-defined tests/scripts:** `origin = developer_defined`; scripts stored as `script` artifacts, run only in the sandbox, always risk-classified (default `medium`, never auto-run until reviewed).

## Deterministic-first and cost limits
Order of work for analysis/planning/triage: deterministic code and tool output → cached/known-pattern lookup → LLM only for remaining reasoning. Every LLM call is preceded by a budget check against `policies.llm_limits` (`max_tokens_per_run`, `max_cost_usd_per_run`, `max_cost_usd_per_day`) and recorded in `llm_usage`; over-budget calls are refused and logged (`blocked_by_budget`). Model/budget values are configuration, not code.

## Extensible tool integrations
Each tool (pytest, Playwright, Semgrep, Bandit, ZAP, axe-core, etc.) is an **adapter** implementing: `capabilities()` (application types, risk level, prerequisites), `plan(snapshot) → planned_tests`, `build_command(planned_test) → argv` (no shell strings), `parse(output) → results/findings candidates`, and a declared sandbox profile (network, resources, image). Adapters are registered in code/config; `planned_tests.tool` must name a registered adapter. New tools = new adapter + registry entry + tests, no schema change.

## Evidence storage
- Bytes: artifact store via an interface (`put/get/delete/exists`, key = `projects/{project_id}/runs/{run_id}/{artifact_id}`), never served by path. Metadata, hash, size, type, redaction/validation state and retention live in `public.artifacts`.
- Collected from sandbox by a worker, **redacted** (secret patterns, configured env values) before storage; `redaction_status` records it. Raw unredacted output is not retained.
- Download endpoints authorize through `project_id`, stream with `Content-Disposition: attachment` and `X-Content-Type-Options: nosniff`, and write an audit event.
- A finding may be `confirmed` only with ≥1 evidence artifact (enforced in the database). "Not run" and "inconclusive" are first-class states; nothing is reported as passed without a stored result.

## Normal run flow
Request → authenticate session → authorize (project access, source/target authorization, policy) → deterministic analysis/plan → plan review (risk, approvals) → approvals recorded → create run + batches (`queued`) → enqueue → worker revalidates → sandbox runs approved commands → collect/redact artifacts → write results → classify findings (evidence required) → optional AI investigation (budgeted) → regression-test proposal → verification run → UI shows evidence. Every step writes `job_events`/`audit_events`.

## Boundaries
- LangGraph coordinates reasoning; long-running execution stays in workers/sandbox. No endpoint exposes arbitrary command execution.
- LLM output never bypasses authorization, approval, or sandbox policy; it is parsed into validated structures and re-checked by deterministic policy code.
- Observability claims limited to what is actually instrumented/ingested.

## Open items
Sandbox isolation level (Q6), Celery PoC (Q8), artifact production store and secrets management (Q10), localhost exposure (Q26), repo provider credentials (Q25) — see `docs/OPEN_QUESTIONS.md`.
