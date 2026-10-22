# Sentinel AI — Implementation Plan

> **Status:** Initial plan — decisions can change through documented updates.
>
> **Purpose:** This is the build and progress-tracking document. `Sentinel_AI_Full_Project_Blueprint.md` remains the product requirements source of truth. This plan translates those requirements into technical choices, repository structure, implementation stages, acceptance criteria, and verification steps.
>
> **Working rule:** Do not treat a planned feature as implemented until its acceptance criteria and verification are recorded.

## 1. Project Goal

Build Sentinel AI as an evidence-driven application quality platform that can analyze supported projects, plan relevant tests, execute approved checks in isolated environments, collect evidence, investigate failures, propose regression tests, verify fixes, monitor observability signals, and retain an auditable history.

The differentiator is the connected workflow—not replacing existing testing tools or simply generating test cases.

## 2. Initial Technical Decisions

These are the recommended starting choices. Record later changes in `docs/decisions/` rather than silently changing the architecture.

| Area | Initial decision | Rationale |
|---|---|---|
| Frontend | React + Vite + JavaScript (changed from TypeScript by owner decision, see ADR-0001 addendum) | Familiar ecosystem, simpler setup |
| Frontend routing | React Router | Clear page and role-based route structure |
| UI styling | CSS variables + a consistent component system; choose any UI library only if it saves time and supports accessibility | Avoid locking into a heavy design system too early |
| Backend | Python + FastAPI | API validation, async support, clear service boundaries |
| Python dependency/environment manager | Poetry | Reproducible dependencies and lockfile |
| Agent orchestration | LangGraph | Conditional workflows, state, branching, and controlled agent steps |
| LLM provider | Gemini API initially, behind a provider/service boundary | Avoid unnecessary model calls and reduce provider lock-in |
| Main database | PostgreSQL | Durable relational records, permissions, run history, findings, and audit data |
| Vector search | Not required initially; add pgvector only if an evidence-retrieval feature needs semantic search | Avoid unnecessary infrastructure |
| Background jobs | Celery + Redis | Suitable initial choice for queued, retryable, long-running work and worker separation |
| Job state/history | PostgreSQL | Durable source of truth; Redis is not the permanent audit database |
| Test execution isolation | Dedicated Docker execution containers, with hardened runtime settings | Separate target code and dependencies from the platform backend |
| QA | pytest and Playwright | Reuse established Python and browser test tooling |
| Static security | Semgrep and Bandit | Source-level security checks |
| Dynamic security | OWASP ZAP, initially in a controlled non-production scope | Dynamic checks require explicit target authorization and safeguards |
| Accessibility | axe-core integrated with Playwright | Automated checks for applicable UI flows |
| Telemetry | OpenTelemetry conventions and instrumentation | Correlate traces and execution metadata where supported |
| Artifact storage | Local artifact directory for development behind an interface; choose object storage for production later | Avoid storing large logs/screenshots/reports in relational rows |
| API style | Versioned REST API under `/api/v1` | Simple frontend/backend contract |
| Deployment development | Docker Compose | Repeatable local services |
| CI | GitHub Actions when repository and checks are established | Automate lint, type checks, tests, and builds |
| Schema changes | Versioned database migrations | Reviewable and repeatable schema evolution |
| API documentation | FastAPI-generated OpenAPI | Keep API contract discoverable |

### Important technology notes

- The selected stack is a starting decision, not a claim that every integration is already installed or configured.
- Avoid a vector database, Kubernetes, multiple model providers, and elaborate distributed infrastructure until the requirements justify them.
- Celery + Redis should be validated with a small proof of concept for job progress, cancellation, retries, worker restarts, and duplicate delivery before relying on it for large batches.
- Docker is useful isolation but is not a complete security boundary. Untrusted-code execution requires additional hardening and may eventually need a stronger isolation technology for high-risk workloads.
- Do not install target-project dependencies into Sentinel AI's backend Poetry environment.
- Never store API keys in source code, frontend environment variables, committed settings, logs, or test artifacts.

## 3. Repository Structure

Use this as the target layout. Create detailed framework-specific subfolders when the corresponding stage reaches them; avoid creating empty placeholder files merely to fill the tree.

```text
sentinel-ai/
├── .github/
│   └── workflows/
│       ├── backend-ci.yml
│       └── frontend-ci.yml
├── backend/
│   ├── src/
│   │   └── sentinel_ai/
│   │       ├── api/
│   │       ├── core/
│   │       ├── db/
│   │       ├── models/
│   │       ├── schemas/
│   │       ├── repositories/
│   │       ├── services/
│   │       ├── jobs/
│   │       ├── orchestration/
│   │       ├── agents/
│   │       ├── execution/
│   │       ├── integrations/
│   │       └── main.py
│   ├── tests/
│   │   ├── unit/
│   │   ├── integration/
│   │   └── security/
│   ├── migrations/
│   ├── pyproject.toml
│   ├── poetry.lock
│   ├── .env.example
│   ├── CLAUDE.md
│   ├── Dockerfile
│   ├── Dockerfile.dev
│   └── README.md
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   ├── routes/
│   │   ├── components/
│   │   ├── features/
│   │   ├── hooks/
│   │   ├── services/
│   │   ├── types/
│   │   ├── utils/
│   │   └── main.jsx
│   ├── tests/
│   ├── public/
│   ├── package.json
│   ├── package-lock.json
│   ├── .env.example
│   ├── CLAUDE.md
│   ├── Dockerfile
│   ├── Dockerfile.dev
│   └── README.md
├── docs/
│   ├── architecture/
│   │   ├── SYSTEM_ARCHITECTURE.md
│   │   ├── FILE_STRUCTURE.md
│   │   ├── API_DESIGN.md
│   │   ├── JOB_AND_SANDBOX_DESIGN.md
│   │   └── AGENT_WORKFLOWS.md
│   ├── decisions/
│   │   └── ADR-0001-initial-technology-stack.md
│   ├── DATABASE_SCHEMA.md
│   ├── SECURITY_AND_SAFETY.md
│   ├── TEST_STRATEGY.md
│   ├── IMPLEMENTATION_PLAN.md
│   └── Sentinel_AI_Full_Project_Blueprint.md
├── docker-compose.yml
├── docker-compose.prod.yml
├── CLAUDE.md
├── settings.json
├── README.md
└── .gitignore
```

### Structure rules

- `backend/src/sentinel_ai/` contains platform backend code only.
- `backend/execution/` and the worker execution service coordinate isolated runs; target project code must not execute inside the API process.
- `backend/agents/` contains narrowly scoped reasoning components; deterministic services should not be wrapped in an agent without a reason.
- `backend/orchestration/` contains LangGraph graph definitions and state transitions.
- `backend/jobs/` contains Celery task definitions and queue-facing job coordination.
- `backend/repositories/` owns database access patterns; `services/` owns application behavior.
- `frontend/features/` groups UI by product area, such as projects, test runs, findings, observability, and administration.
- `docs/` holds architecture decisions and cross-cutting design. Service-specific setup stays in the matching service README.
- `docker-compose.yml` is for local development. `docker-compose.prod.yml` is a production reference and must not be treated as production-ready until secrets, networking, persistence, TLS, health checks, and operational controls are reviewed.
- Keep `.env` files untracked. Commit only safe `.env.example` files.

## 4. Required Instruction and Planning Files

### Root `CLAUDE.md`

Must explain:
- What Sentinel AI is and is not.
- The source-of-truth documents.
- How to choose the relevant frontend/backend instructions.
- Security boundaries and authorization rules.
- No fabricated test results or findings.
- No unapproved production/destructive actions.
- Token-efficient workflow: inspect only relevant files, make focused changes, avoid repeated full-document reads.
- Verification and reporting expectations.
- How to update the implementation tracker and decision records.

### `frontend/CLAUDE.md`

Must explain:
- Frontend boundaries and API communication through the shared client/service layer.
- JavaScript (JSX) conventions and component organization (TypeScript dropped by owner decision).
- Loading, error, empty, and progress states.
- Accessible UI, keyboard support, and semantic markup.
- Role-based UI as a usability feature only; backend authorization remains authoritative.
- Never expose secrets or provider keys in browser code.
- Frontend test and build commands.

### `backend/CLAUDE.md`

Must explain:
- FastAPI, Poetry, layering, configuration, and migration conventions.
- Authentication/authorization checks belong on the server.
- PostgreSQL is the durable source of truth.
- Celery/Redis are for job delivery/queueing; job history must be persisted.
- Target code runs only in a restricted execution environment.
- Never expose platform secrets to test containers.
- Enforce target authorization, execution budgets, network rules, and approval policies.
- Keep deterministic operations out of LLM calls.
- Validate external inputs, redact secrets, and avoid logging sensitive payloads.
- Backend test and migration commands.

### `settings.json`

Use for machine-readable project scope and guardrails, not as a replacement for prose instructions. Start with a small schema containing:
- `project_name`
- `project_status`
- `supported_application_types`
- `in_scope_capabilities`
- `out_of_scope`
- `security_defaults`
- `approval_required_for`
- `implementation_stage`
- `decisions_pending`

Keep secrets out of this file. Validate its schema when code begins reading it.

### Documentation set

- `docs/IMPLEMENTATION_PLAN.md`: This stage tracker.
- `docs/architecture/SYSTEM_ARCHITECTURE.md`: Components, boundaries, flows, trust zones, and deployment context.
- `docs/architecture/FILE_STRUCTURE.md`: Folder responsibilities and import/dependency direction.
- `docs/architecture/API_DESIGN.md`: API conventions, endpoints, request/response examples, and errors.
- `docs/DATABASE_SCHEMA.md`: Tables, relationships, indexes, ownership, retention, and migration notes.
- `docs/architecture/AGENT_WORKFLOWS.md`: LangGraph workflows, state, conditional routing, and agent boundaries.
- `docs/architecture/JOB_AND_SANDBOX_DESIGN.md`: Celery queues, job lifecycle, cancellation, worker behavior, container isolation, and artifact flow.
- `docs/SECURITY_AND_SAFETY.md`: Roles, project scope, approval rules, sandbox controls, data handling, and threat assumptions.
- `docs/TEST_STRATEGY.md`: Unit/integration/E2E/security/accessibility tests, fixtures, and acceptance criteria.
- `docs/decisions/`: Short architecture decision records (ADRs) for meaningful choices or changes.
- `backend/README.md` and `frontend/README.md`: Service-specific setup, environment variables, and commands.
- Root `README.md`: Product summary and developer quickstart.

Do not create all documentation in a single huge generation without checking consistency. Create and maintain each document at the stage when it becomes useful.

## 5. Product Roles and Access Model

### Developer
- View authorized projects and their test history.
- Select permitted test cases/categories and start, cancel, or rerun permitted test batches.
- Inspect evidence, logs, traces, findings, and reports.
- Review or propose regression tests.
- Cannot bypass target authorization, security policy, sandbox restrictions, or approval gates.

### Admin
- Manage users/project access and testing policies within assigned scope.
- Configure integrations, thresholds, and permitted execution settings.
- Approve higher-risk actions when policy grants that authority.
- Review project/team history and audit activity within scope.

### Super Admin
- Manage platform-wide policies, administrative access, and global configuration.
- Audit privileged activity and manage platform-level controls.
- Does not remove the need to record and audit privileged actions.

### Access rules
- Enforce authorization in backend endpoints and job workers, not just in the frontend.
- Scope every project, run, artifact, finding, and log to the correct owner/team.
- Workers must revalidate that a run is authorized and still permitted before execution.
- Developers cannot run tests against targets outside their authorized scope.
- Destructive, intrusive, production-targeted, or high-risk tests require explicit approval under configured policy.
- Keep an audit record of sensitive actions and approval decisions.
- The precise authentication/session method and permission matrix must be defined before protected routes are implemented.

## 6. Initial System Architecture

### Major components
1. **React frontend:** Project management, test plan review, execution progress, findings, alerts, history, and chatbot UI.
2. **FastAPI backend:** Authentication, authorization, project APIs, plan/run APIs, evidence APIs, and UI-facing services.
3. **PostgreSQL:** Users, access rules, projects, plans, runs, batches, results, findings, approvals, alerts, and audit records.
4. **Redis:** Celery broker and queue coordination; not the permanent history store.
5. **Celery workers:** Execute durable queued tasks and coordinate job lifecycle.
6. **Sandbox executor:** Creates and controls restricted containers for target project commands and testing tools.
7. **LangGraph orchestration:** Conditional reasoning workflow for analysis, planning, investigation, and verification.
8. **Gemini provider service:** Centralized model calls with timeouts, token limits, usage recording, and error handling.
9. **Artifact storage interface:** Stores reports, screenshots, selected logs, and other larger artifacts outside relational rows.
10. **Telemetry integration:** OpenTelemetry-compatible traces/metrics/log correlation where available.

### Normal test workflow
1. User selects an authorized project and requests analysis or a test run.
2. Backend verifies identity, project access, target scope, and policy.
3. Project analysis and test planning use deterministic discovery first; an LLM is called only if interpretation is needed.
4. The user sees the proposed plan and relevant risk/approval requirements.
5. Low-risk tests may execute according to configured policy; high-risk actions wait for explicit approval.
6. Backend persists the run and batch records, then enqueues work.
7. Celery worker claims the job and verifies it is still authorized and not cancelled.
8. Sandbox executor launches a restricted environment and runs approved commands.
9. Results and artifacts are collected; sensitive data is redacted where practical.
10. PostgreSQL status and progress are updated.
11. Relevant findings are classified; AI investigation is invoked only when useful.
12. Failure-to-test workflow may propose a regression test for developer review.
13. Fix verification reruns the relevant test in a controlled environment.
14. The UI shows status, evidence, and history.

### Conditional routing examples
- Tests pass and no unusual evidence appears → persist results; no investigation agent call.
- Ordinary test failure → collect diagnostics; invoke failure investigation only if configured or the failure is significant.
- Security scanner finding → normalize result; request deeper verification when severity/policy warrants it.
- Runtime log anomaly → apply deterministic filters/thresholds first; alert or invoke analysis if meaningful.
- Regression test proposal → save as proposed; do not silently merge code or run high-risk actions.
- Missing required permission/scope → block before dispatching a job.

## 7. Background Jobs, Batches, Cancellation, and Recovery

### Initial choice: Celery + Redis
Use Celery with Redis as the initial job queue. Validate the implementation with a small proof of concept before scaling.

### Job model
A test run may contain multiple batches; a batch may contain multiple test cases. Persist records for:
- Run status and requesting user.
- Project and authorized target.
- Selected test plan and policy snapshot.
- Batch status and assigned worker.
- Individual test results.
- Start/end times and progress.
- Retry count and failure reason.
- Cancellation request and final cancellation outcome.
- Artifact/evidence references.

### Lifecycle
`QUEUED → DISPATCHED → RUNNING → COMPLETED | FAILED | CANCELLED | TIMED_OUT | BLOCKED`

A run can also be `CANCEL_REQUESTED` while termination is being processed. Status transitions must be validated and persisted.

### Batch behavior
- Support a configurable batch size and concurrency ceiling.
- Avoid duplicate work where possible; make tasks idempotent or deduplicate by run/batch/test identifiers.
- Retain results from batches completed before cancellation.
- Retry only eligible transient failures, with bounded attempts and backoff.
- Do not retry destructive tests automatically unless explicitly safe and approved.
- Enforce per-user/project queue and resource limits.

### Cancellation behavior
- Queued jobs: revoke/remove from dispatch and mark cancelled in PostgreSQL.
- Running jobs: set a durable cancellation request; worker checks it and asks the executor to terminate the sandbox.
- Confirm cancellation only after the worker/executor acknowledges termination or records a bounded timeout/escalation outcome.
- Do not rely on Redis revocation alone as the source of truth.
- Ensure cleanup runs after success, failure, timeout, or cancellation.
- On worker restart, reconcile stuck runs and either resume safely, retry eligible work, or mark the run interrupted/failed with evidence.

### Cron/scheduled jobs
Cron is not the same as background processing. Scheduled recurring checks may be added later; ordinary user-triggered long-running work uses the queue/worker system.

## 8. Sandbox Security Requirements

Sandboxing is a core security boundary and needs a dedicated design document before untrusted code execution is enabled.

Minimum initial controls:
- Separate execution containers from API and worker control services.
- Use non-root execution, drop unnecessary Linux capabilities, and apply seccomp/AppArmor or equivalent host controls where available.
- Apply CPU, memory, process-count, disk, and wall-clock limits.
- Use read-only base images where practical and a disposable workspace for each run.
- Do not mount the Docker socket into target-code containers.
- Never mount backend secrets, database credentials, Redis credentials, host home directories, or unrelated project files into a sandbox.
- Deny network access by default; allow only narrowly scoped destinations when a test needs them and the target is authorized.
- Avoid privileged containers; pin trusted images and scan/update them.
- Validate archive paths and reject path traversal, symlinks escaping the workspace, oversized archives, and decompression bombs.
- Treat repository files, logs, prompts, and tool output as untrusted data.
- Sanitize/redact credentials and sensitive output before persistence or display.
- Use execution timeouts and reliable process/container cleanup.
- Audit target scope, approval, commands, image versions, and execution outcome.
- Do not test public or production targets without explicit authorization and a documented scope.

Docker alone does not guarantee strong isolation against hostile code. Evaluate rootless Docker, gVisor, Kata Containers, or a separate disposable VM for higher-risk use cases before broad untrusted execution.

## 9. Initial Database Design Direction

Detailed SQL and migrations belong in `docs/DATABASE_SCHEMA.md` and migration files. Start with normalized entities and explicit ownership.

### Initial entity groups
- **Identity:** `users`, `roles` or role assignments, `sessions`/credentials according to the selected auth model.
- **Access:** `teams` or organizations if needed, `project_memberships`, permission/policy records.
- **Projects:** `projects`, `project_sources`, source/analysis snapshots, integration configurations.
- **Planning:** `test_plans`, `planned_tests`, approvals and plan versions.
- **Execution:** `test_runs`, `test_batches`, `test_cases` or test definitions, `test_results`, job events.
- **Findings:** `findings`, `finding_events`, verification attempts, related regression tests.
- **Observability:** alert records, correlated trace/log references, anomaly events.
- **Artifacts:** metadata and secure storage references for logs, reports, screenshots, coverage files, and evidence.
- **Audit:** security-sensitive actions, approvals, policy changes, and administrative actions.

### Data rules
- Use stable IDs, foreign keys, appropriate indexes, timestamps, and explicit status enums/constraints.
- Store large artifacts outside relational rows; keep metadata and access-controlled references in PostgreSQL.
- Do not store raw secrets or unnecessary sensitive prompt/log content.
- Scope queries and artifact retrieval by authorization, not just by frontend filters.
- Preserve history needed for audit and regression comparisons.
- Define retention/deletion policy before production.
- Use versioned migrations; do not manually alter a live schema without a migration.
- Add pgvector only if semantic evidence retrieval is required after evaluating simpler retrieval approaches.

## 10. API Design Direction

Use `/api/v1` for versioned REST endpoints. Exact schemas and route names will be documented in `docs/architecture/API_DESIGN.md`.

Likely API groups:
- `/auth/*` — sign-in/out and current identity, depending on chosen auth design.
- `/users/*` and `/admin/*` — role-controlled user/admin operations.
- `/projects/*` — project creation, source registration, analysis, and membership.
- `/test-plans/*` — create, inspect, update, approve, and reject plans.
- `/test-runs/*` — start, inspect, cancel, and rerun authorized runs.
- `/test-runs/{id}/batches/*` — batch progress and results.
- `/findings/*` — finding details, evidence, verification history, and status.
- `/alerts/*` — observability alerts and acknowledgement.
- `/artifacts/*` — authorized artifact metadata/download access.
- `/reports/*` — report generation and retrieval.
- `/chat/*` — evidence-grounded questions, with access-filtered retrieval.
- `/health/*` — service health/readiness without exposing secrets.

API requirements:
- Validate all request data.
- Apply authorization on every protected operation.
- Use consistent error envelopes and status codes.
- Do not expose arbitrary command execution through public API endpoints.
- Use polling initially for job progress; consider Server-Sent Events or WebSockets only if the UX needs them.
- Never trust a run/project ID alone as proof of access.

## 11. Agent and LangGraph Design

The system should not create an LLM agent for every capability. Keep agent responsibilities narrow and invoke them conditionally.

### Deterministic services first
Use ordinary Python/services for:
- Repository file listing and supported file checks.
- Framework and dependency detection where rules are sufficient.
- Permission and target-scope checks.
- Queue dispatch and cancellation.
- Running tools and collecting exit codes.
- Coverage parsing and simple comparisons.
- Thresholds, status transitions, retries, and resource limits.
- Evidence metadata and audit events.

### Reasoning workflows
Use LangGraph and Gemini when a task benefits from interpretation:
- **Project interpretation:** Explain architecture from discovery evidence and state uncertainty.
- **Test planning:** Propose relevant tests from requirements and analysis output.
- **Failure investigation:** Correlate diagnostics and rank plausible causes.
- **Regression-test proposal:** Draft tests based on reproducible/verified failure details.
- **Security finding triage:** Interpret tool output and recommend verification, without overriding deterministic policy.
- **Report synthesis/chat:** Summarize authorized evidence with references.

### Initial graph patterns
1. **Analysis graph:** Input validation → deterministic discovery → optional LLM interpretation → persist analysis.
2. **Planning graph:** Load analysis/requirements → identify applicable capabilities → optional LLM test proposals → policy/risk checks → plan review.
3. **Execution workflow:** Authorize → enqueue → worker → sandbox/tool execution → persist results. Keep the actual long-running execution in the worker system; LangGraph coordinates reasoning and stateful decisions, not unrestricted shell execution.
4. **Investigation graph:** Collect evidence → classify failure → optional analysis → propose cause/tests → human review when needed.
5. **Verification graph:** Load finding/fix context → select relevant checks → execute safely → compare evidence → update status with limitations.

### LLM cost controls
- Do not call a model for every test or every log line.
- Use deterministic filtering, deduplication, thresholds, and grouping before any LLM call.
- Cache reusable analysis results using source/version hashes where safe.
- Send focused evidence excerpts, not entire repositories or huge logs.
- Bound context, output tokens, retries, execution time, and per-project cost.
- Record model, usage, latency, result, and estimated cost metadata.
- Reuse model outputs only when their inputs and project version are unchanged.
- Keep secrets and irrelevant personal data out of prompts.
- Use structured output schemas and validate outputs before acting.
- Never allow an LLM output to bypass authorization, approval, or sandbox policy.

## 12. Observability and Alert Flow

Initial flow:
1. Receive supported logs/traces or execution events.
2. Normalize and redact sensitive fields.
3. Apply deterministic severity/threshold and deduplication rules.
4. Persist event/alert metadata and evidence references.
5. Notify the appropriate authorized users in the UI.
6. Invoke an analysis agent only for selected meaningful events.
7. If useful, propose a reproduction or regression test.
8. Require review/approval as policy dictates.
9. Store the test result and link it to the originating alert.

Do not claim full application observability unless the target application is instrumented and its telemetry is connected. Log ingestion, trace ingestion, and application instrumentation are separate capabilities and should be represented honestly in the UI.

## 13. Testing and Quality Gates

### Backend
- Unit tests for services, permissions, policy decisions, state transitions, and parsers.
- API integration tests against a test database.
- Job tests for retries, cancellation, idempotency, and worker recovery.
- Sandbox tests proving secrets are not mounted and restrictions are applied.
- Security tests for cross-project access and unauthorized execution.

### Frontend
- Component and utility tests.
- Route/role UI tests.
- API error, loading, empty, and progress-state tests.
- Playwright end-to-end flows.
- axe-core checks on key pages and flows.

### Integration
- Project intake → plan → approval/policy → queued run → sandbox → persisted result → UI evidence.
- Cancel queued and running work.
- Worker restart and interrupted-run recovery.
- Finding → proposed regression test → approval → execution → verification.
- User A cannot read User B's project/run/artifact without permission.

No stage is complete solely because code was written. Record actual commands and outcomes. Tests that were not run must be labeled as not run.

## 14. Claude Instructions and Skills

### Root `CLAUDE.md`
Keep global project purpose, boundaries, safety requirements, token-efficient workflow, source-of-truth docs, and documentation update rules.

### `frontend/CLAUDE.md`
Keep UI architecture, JavaScript conventions, accessibility, API client rules, role-based display expectations, and frontend test/build commands.

### `backend/CLAUDE.md`
Keep backend layering, Poetry commands, database migration rules, authorization, queue/sandbox safety, evidence integrity, and backend test commands.

### Optional tools/skills
Evaluate only when they provide a clear benefit:
- **UI/UX/accessibility skill:** Useful when establishing dashboard patterns and accessible interactions.
- **Superpowers:** Use only if available and useful for disciplined development workflows.
- **Graphify:** Consider if it helps understand the codebase/dependencies after enough code exists.
- **OmniRoute/NVIDIA-related tooling:** Consider only if a concrete routing or inference requirement justifies it.
- **Other skills:** Add a task-specific instruction only when needed.

Verify names, availability, compatibility, and value before installing or using a tool. Do not install everything on a list. “Ponytail” needs clarification as a specific tool/skill before it can be recommended. Skills do not replace repository instructions or tests.

## 15. First-Time Claude Workflow

The user should not have to manually author large files or repeatedly paste the entire blueprint.

For each substantial task:
1. Open the project root in Claude Code.
2. Ask Claude to read the root `CLAUDE.md`, the relevant service `CLAUDE.md`, the implementation plan, and only the specific documents needed for the task.
3. Ask it to work on one stage or bounded task at a time.
4. Ask it to inspect current files before editing and preserve unrelated work.
5. Ask it to update the relevant tracker/documents when a decision or implementation changes.
6. Ask it to run appropriate safe checks and report exactly what ran.
7. The user manually executes small, low-risk commands when practical; Claude should provide the exact command and expected result.
8. Review diffs and approvals before merging or running risky operations.

Do not ask the user to run destructive or security-sensitive commands without explaining them and confirming the target. Avoid repeated full-blueprint reads for small changes.

## 16. Stage-by-Stage Implementation Tracker

**Status values:** `NOT STARTED`, `IN PROGRESS`, `BLOCKED`, `DONE`, `DEFERRED`.

Update the status, date, evidence, and unresolved decisions for each stage as work proceeds. Do not mark a stage DONE until its acceptance criteria are met.

### Stage 0 — Confirm scope and decisions
**Status:** DONE pending owner review (2026-10-22) — blueprint reviewed against ADR-0001; stack (Q14) and first-release scope (Q7) confirmed by the owner and recorded in ADR-0001 (now Accepted), OPEN_QUESTIONS and `settings.json`. Q15–Q24 are consciously deferred to Stage 2 or later. Celery+Redis and Docker isolation are chosen but not yet validated (Q6, Q8).

**First-release scope (confirmed 2026-10-22)**
- Application types: web apps, REST APIs, AI apps (RAG/agents).
- Inputs: Git repository, ZIP upload, localhost URL, live development/staging URL.
- Testing modes: automatic recommendations, prompt-based planning, developer-defined tests/scripts.
- Excluded: MiroFish.
- Requirements: evidence-backed findings; deterministic checks before LLM calls where practical, with cost limits; extensible testing-tool integrations; restricted execution for project code and custom scripts; production testing blocked by default unless explicitly authorized and approved.

**Work**
- Review the requirements blueprint.
- Confirm the initial stack in this plan.
- Record initial technology ADR.
- Identify first-release scope and explicit exclusions.
- Define initial security boundaries and what requires approval.

**Acceptance criteria**
- Requirements and implementation plan are consistent.
- Initial decisions and open questions are documented.
- No code implementation has started prematurely.

### Stage 1 — Initialize repository and Claude context
**Status:** DONE pending owner review (2026-10-21) — acceptance criteria met by observed checks, see section 21. Stage 0 decisions confirmed 2026-10-22; clean-clone verification done 2026-10-22 (section 21). Awaiting owner sign-off.

**Frontend work**
- Create `frontend/` directory.
- Initialize React + Vite + JavaScript (owner decision; plan originally said TypeScript).
- Create frontend `.env.example`, `README.md`, and `CLAUDE.md`.

**Backend work**
- Create `backend/` directory.
- Initialize Poetry project for supported Python version.
- Create `src/sentinel_ai/`, tests, migration directory, `.env.example`, `README.md`, and `CLAUDE.md`.

**Shared work**
- Create root `CLAUDE.md`, root README, `settings.json`, `.gitignore`, and docs tree.
- Place/copy the requirements blueprint into `docs/`.
- Create this implementation tracker.
- Add architecture/API/schema/security/test strategy document skeletons only when their content is ready to be defined.

**Acceptance criteria**
- Frontend and backend are separate.
- Root and scoped instructions explain boundaries.
- No secrets are committed.
- Basic frontend and backend hello-world checks work.
- Setup commands are documented and reproducible.

### Stage 2 — Architecture, data model, and API contracts
**Status:** DONE pending owner review (2026-10-22), with one open item: the migrations are verified on a disposable database but **not yet applied to the real `sentinel-ai` database** (see Q28). Owner confirmation of ADR-0002 / permission matrix (Q5, Q27) also pending. Evidence: section 21.

**Work**
- Create system architecture and file structure docs.
- Define authentication approach and detailed role/permission matrix.
- Define initial relational schema and indexes.
- Define API conventions, error format, and endpoint contracts.
- Define run/batch/job state transitions and audit events.
- Define artifact metadata and retention assumptions.

**Acceptance criteria**
- `DATABASE_SCHEMA.md` agrees with API and workflow docs.
- Project ownership and access scope are explicit.
- Migrations can create the initial schema from an empty database.
- No application feature depends on undocumented schema assumptions.

### Stage 3 — Local development services and configuration
**Status:** DONE (2026-10-22) — owner-reported live verification plus Claude's automated checks (section 21). Redis is unavailable locally and is deliberately deferred to Stage 7.

**Work**
- Add PostgreSQL and Redis to development Compose.
- Configure backend settings and connection validation.
- Add database migration tooling and health checks.
- Add safe local example configuration.
- Add baseline linting, formatting, type checking, and test commands.

**Acceptance criteria**
- Services start from documented commands.
- Secrets are environment-supplied and not committed.
- Backend can connect to the database and run migrations.
- Health/readiness checks work without exposing sensitive values.

### Stage 4 — Identity, roles, project ownership, and audit
**Status:** NOT STARTED

**Work**
- Implement selected authentication/session strategy.
- Implement Developer, Admin, and Super Admin permissions.
- Implement project ownership/membership and server-side authorization.
- Record privileged actions and approval decisions.
- Add tests for cross-project and cross-role access.

**Acceptance criteria**
- Backend enforces permissions on every protected route.
- UI role controls do not act as the only security check.
- Unauthorized users cannot read projects, runs, artifacts, or findings.
- Sensitive actions are auditable.

### Stage 5 — Project intake and deterministic analysis
**Status:** NOT STARTED

**Work**
- Support initial source input method(s), then add additional input types incrementally.
- Validate archive paths, file sizes, file types, and input scope.
- Detect common languages, frameworks, tests, and configuration.
- Record source snapshot/version and analysis results.
- Identify unavailable evidence and initial coverage gaps.

**Acceptance criteria**
- Analysis results distinguish detected facts from inferences.
- Invalid or oversized input is rejected safely.
- Project/source ownership is enforced.
- A repeatable analysis result is persisted and visible.

### Stage 6 — Test plans and approval policies
**Status:** NOT STARTED

**Work**
- Define test-plan and planned-test models.
- Map project type/capabilities to applicable test categories.
- Generate a transparent plan with targets, reasons, risk, prerequisites, and expected evidence.
- Implement policy routing: permitted low-risk checks can proceed automatically; high-risk actions require approval.
- Build frontend plan review/edit/approve/reject states.

**Acceptance criteria**
- Users see what is planned before execution.
- Approval rules are enforced server-side.
- Unavailable or inapplicable checks are explained.
- The plan snapshot is linked to the resulting run.

### Stage 7 — Job queue, batches, cancellation, and recovery
**Status:** NOT STARTED

**Work**
- Add Celery + Redis and separate worker process.
- Define durable PostgreSQL run/batch/task status.
- Implement batch sizing, concurrency limits, bounded retries, and idempotency.
- Implement queued-job cancellation and running-job cancellation requests.
- Implement worker restart reconciliation and timeout handling.
- Expose progress and status through API.

**Acceptance criteria**
- Queued jobs can be cancelled.
- Running jobs request termination of their sandbox and report the outcome.
- Completed batch results survive cancellation of later batches.
- Duplicate task delivery does not silently duplicate unsafe work.
- Stuck jobs are reconciled and visible.
- Worker restart behavior is tested and documented.

### Stage 8 — Sandboxed execution foundation
**Status:** NOT STARTED

**Work**
- Create a dedicated sandbox executor interface.
- Build disposable execution containers with non-root users and resource/time limits.
- Default network access to denied.
- Ensure no Docker socket, host home, backend secrets, or platform credentials enter target containers.
- Validate archive extraction and workspace boundaries.
- Implement timeout, cancellation, cleanup, and artifact collection.
- Document threat model and residual risks.

**Acceptance criteria**
- A sample test command executes only inside the sandbox.
- Sandbox cannot access protected backend secrets or unrelated workspaces.
- CPU, memory, process, time, filesystem, and network policies are enforced as configured.
- Containers/workspaces are cleaned after success, failure, timeout, and cancellation.
- Risky or unauthorized targets are blocked before execution.

### Stage 9 — First QA execution path
**Status:** NOT STARTED

**Work**
- Integrate one initial test runner (recommended: pytest for Python projects).
- Parse and normalize results.
- Store test cases/results and evidence references.
- Add run progress, result detail, and frontend history.
- Add safe Playwright execution later in this stage or the next increment, after browser sandboxing is validated.

**Acceptance criteria**
- User can select a permitted test plan, run it, observe progress, cancel it, and inspect evidence.
- Result states distinguish pass, fail, skip, blocked, timed out, and not run.
- Failed-to-start is not reported as a test failure or pass.
- Run ownership and artifact authorization are enforced.

### Stage 10 — Security integrations and finding verification
**Status:** NOT STARTED

**Work**
- Integrate static checks such as Semgrep and Bandit.
- Add dependency checks if selected and configured.
- Integrate OWASP ZAP only for approved, explicitly scoped targets and controlled environments.
- Normalize findings and deduplicate related alerts.
- Implement finding states and verification attempts.
- Add approval gates for intrusive checks.

**Acceptance criteria**
- Every finding links to source tool output/evidence.
- Scanner output is not automatically labeled confirmed.
- Unauthorized targets and disallowed scan profiles are blocked.
- Findings show confidence, verification state, and limitations.

### Stage 11 — LangGraph workflows and selective Gemini use
**Status:** NOT STARTED

**Work**
- Implement analysis, planning, investigation, regression-test proposal, and verification graph workflows where justified.
- Define structured state and validated output schemas.
- Add timeouts, bounded retries, model usage tracking, and token/cost limits.
- Add evidence filtering and redaction before model calls.
- Ensure model output cannot override permission or approval policies.

**Acceptance criteria**
- Deterministic work does not trigger needless LLM calls.
- Graph transitions and agent decisions are traceable.
- Invalid model output is rejected or handled safely.
- Model failures degrade gracefully and are recorded.
- Usage/cost metadata is recorded where provider data allows.

### Stage 12 — Observability, alerts, and failure-to-test loop
**Status:** NOT STARTED

**Work**
- Define supported log/trace ingestion and instrumentation paths.
- Normalize and redact events.
- Add deterministic filtering, deduplication, and configurable thresholds.
- Correlate events with projects, runs, tests, and findings where identifiers exist.
- Add UI alerts and acknowledgement.
- Use investigation workflow selectively.
- Propose regression tests from sufficiently evidenced failures.

**Acceptance criteria**
- Alerts show supporting evidence and do not claim a root cause without verification.
- Missing telemetry is clearly disclosed.
- A failure can produce a proposed regression test linked to the original event.
- Tests are not silently committed or run beyond configured permissions.
- Sensitive log fields are redacted according to policy.

### Stage 13 — Accessibility, LLM/agent security, and telemetry
**Status:** NOT STARTED

**Work**
- Integrate axe-core checks into relevant Playwright flows.
- Add relevant LLM/RAG/agent security test scenarios based on the target project capabilities.
- Add OpenTelemetry correlation for platform workflows and supported target integrations.
- Track model/tool calls, latency, retries, token usage, and estimated costs where available.
- Add resource/cost anomaly detection using deterministic rules first.

**Acceptance criteria**
- Accessibility results identify affected elements and criteria, with limitations stated.
- AI/agent security checks are only run when applicable and authorized.
- Telemetry correlates with runs/findings where possible.
- Model-call and cost information is clearly labeled when estimated or incomplete.

### Stage 14 — Evidence-grounded chatbot, reporting, and history
**Status:** NOT STARTED

**Work**
- Build authorized retrieval over project files, test results, findings, logs, traces, and reports.
- Add evidence links/citations in answers.
- Build report generation and run comparison.
- Add user profiles with authorized test history.
- Enforce Developer/Admin/Super Admin visibility rules.

**Acceptance criteria**
- Chat answers use available evidence and disclose missing/inconclusive data.
- It does not invent test results or vulnerabilities.
- Users can only access records and artifacts allowed by their permissions.
- Reports distinguish planned, executed, skipped, blocked, and failed-to-start checks.

### Stage 15 — Regression verification and reliability hardening
**Status:** NOT STARTED

**Work**
- Complete fix-verification workflow.
- Compare repeated runs and reopen regressions.
- Test queue retries, worker crashes, cancellation races, and sandbox cleanup.
- Test rate limits, concurrency limits, artifact access, and sensitive-data handling.
- Review alert noise, false positives, and failure classifications.

**Acceptance criteria**
- Verified resolution requires recorded evidence.
- Regressions are linked to prior findings/tests where possible.
- Failure modes are tested and documented.
- Security and reliability issues found in the review are resolved or explicitly tracked.

### Stage 16 — CI, Docker, deployment readiness, and documentation
**Status:** NOT STARTED

**Work**
- Add GitHub Actions for frontend/backend checks.
- Finalize production and development Dockerfiles.
- Finalize development Compose and review production Compose reference.
- Document environment variables, secrets, migrations, backups, health checks, logging, and recovery.
- Update root/frontend/backend READMEs and architecture diagrams.
- Perform a clean setup from documented instructions.

**Acceptance criteria**
- CI runs the intended checks and reports failures accurately.
- Clean checkout can be set up from documentation.
- Production configuration has been reviewed for secrets, network exposure, persistence, TLS, and operational needs.
- Deployment claims match what has actually been tested.

## 17. Progress Update Template

Append or update this section after meaningful work:

```text
Date:
Stage:
Status: NOT STARTED / IN PROGRESS / BLOCKED / DONE / DEFERRED
Changes made:
Files changed:
Commands actually run:
Test results:
Acceptance criteria met:
Known issues:
Decisions made or changed:
Next action:
```

Keep one current status per stage; use Git history and decision records for detailed historical changes.

## 18. Decision Change Process

The plan is expected to evolve. When a better approach is found:
1. State the problem with the current choice.
2. Compare alternatives against security, reliability, complexity, cost, and developer effort.
3. Record the decision and trade-offs in `docs/decisions/`.
4. Update this plan and any affected architecture/API/schema/security documents.
5. Update the implementation status and migration path.
6. Avoid changing code and documentation inconsistently.

Do not change major dependencies or architecture merely because a tool is popular. Tie changes to a requirement or observed limitation.

## 19. Initial Decisions Still Requiring Validation

The plan makes an initial selection, but these details require a small proof of concept or explicit design before production use:
- Celery + Redis task delivery, cancellation, retries, and worker recovery.
- Docker sandbox threat model and whether stronger isolation is required.
- Exact authentication/session mechanism and role-permission matrix.
- Initial source-input path and supported repository providers.
- Exact database schema and artifact storage provider.
- Model/token budget limits and Gemini model selection.
- Initial CI checks and supported runtime versions.
- Production deployment topology and secrets management.

These are validation tasks, not reasons to leave the entire project undecided.

## 20. Definition of Done for the Project

Sentinel AI is not complete merely because its UI or agents run. A release should demonstrate an end-to-end workflow that:
- Accepts an authorized project input.
- Analyzes it and proposes an explainable plan.
- Enforces risk and approval policy.
- Runs a permitted test in an isolated environment.
- Records durable status and evidence.
- Lets an authorized user inspect or cancel the run.
- Investigates a meaningful failure when appropriate.
- Proposes and verifies a regression test where feasible.
- Retains history and prevents unauthorized cross-project access.
- Reports limitations honestly and passes the relevant automated checks.

## 21. Current Progress Log

```text
Date: 2026-10-21
Stage: 0 and 1 (documentation setup only)
Status: Stage 0 IN PROGRESS; Stage 1 IN PROGRESS (historical entry; superseded by later entries)
Changes made: Created instruction files, settings, .gitignore, architecture/doc skeletons, ADR-0001 (Proposed), OPEN_QUESTIONS. Blueprint added to docs/ (byte-identical to Downloads/Sentinel_AI_Full_Project_Blueprint_Updated.md). This file replaced with the complete plan (byte-identical copy of Sentinel_AI_IMPLEMENTATION_PLAN.md) plus status edits and this log. Removed redundant Sentinel_AI_Project_Overview.md.
Commands actually run: file listing, cmp/md5sum comparisons, cp, rm of the overview, JSON validation of settings.
Test results: none; no code exists.
Acceptance criteria met: none fully.
Known issues: see docs/OPEN_QUESTIONS.md.
Decisions made or changed: none.
Next action: resolve Q9 (tool/version choices) and Q12 (git init), then begin Stage 1 project init on approval.
```

```text
Date: 2026-10-21
Stage: 1 — Initialize repository and Claude context
Status: DONE pending owner review (Stage 0 still IN PROGRESS)
Changes made: git init -b main (no commits). Blueprint reviewed vs ADR-0001/skeletons -> OPEN_QUESTIONS Q14-Q24. Backend: Poetry project (Python 3.12), FastAPI app with GET /api/v1/health, pytest test, Ruff/mypy config, Alembic initialized in backend/migrations (no schema, empty sqlalchemy.url), .env.example, README. Frontend: Vite + React scaffold (originally TS; converted to JavaScript, see amendment entry below) with a static heading, Vitest + Testing Library test, .env.example, README. Updated CLAUDE.md commands, root README, settings.json stage, ADR-0001 addendum.
Files changed: backend/**, frontend/**, README.md, settings.json, docs/OPEN_QUESTIONS.md, docs/decisions/ADR-0001-*.md, docs/IMPLEMENTATION_PLAN.md, backend/CLAUDE.md, frontend/CLAUDE.md.
Commands actually run: poetry install; poetry run pytest / ruff check / ruff format --check / mypy / alembic --help; npm install; npm run lint / test / build.
Test results: backend pytest 1 passed (1 upstream deprecation warning); ruff check and format clean; mypy strict clean (4 files); alembic CLI runs. Frontend oxlint exit 0; vitest 1 passed; build succeeded. NOT run: dev servers, uvicorn live request, Docker, any CI.
Acceptance criteria met: frontend/backend separate; scoped instructions exist; no secrets committed (placeholders only); hello-world checks pass; commands documented. Not verified: reproducibility from a clean checkout (no clean-clone test done).
Known issues: Q14-Q24 in OPEN_QUESTIONS; frontend/backend Dockerfiles, docker-compose and CI intentionally deferred to Stages 3/16.
Decisions made or changed: toolchain confirmed (ADR-0001 addendum); oxlint kept as Vite template default.
Next action: owner review; resolve Q14/Q15/Q7; then Stage 2 (not started).
```

```text
Date: 2026-10-21
Stage: 1 (amendment)
Changes made: Frontend converted from TypeScript to JavaScript per owner request (removed tsconfig*, typescript and @types/*; files renamed to .jsx/.js; build script now `vite build`). Docs updated (frontend CLAUDE.md/README, ADR-0001 addendum, this plan).
Test results: superseded by the verification entry below (the original "re-run (see report)" had no recorded results).
```

```text
Date: 2026-10-22
Stage: 1 (verification after JavaScript conversion)
Status: DONE pending owner review (Stage 0 still IN PROGRESS)
Changes made: docs only. frontend/README.md build comment corrected (no type-check); plan file tree main.tsx -> main.jsx; stale TS/"see report" wording in earlier log entries annotated.
Commands actually run: frontend: npm run lint; npm test; npm run build. backend: poetry run pytest; ruff check .; ruff format --check .; mypy; alembic --help.
Test results: frontend oxlint exit 0; vitest 1 file / 1 test passed; vite build succeeded (16 modules, dist/ emitted). backend pytest 1 passed, 1 warning (starlette/httpx deprecation, Q23); ruff check clean; ruff format 8 files already formatted; mypy no issues in 4 source files; alembic CLI prints usage.
NOT run: dev servers, live uvicorn request, Docker, CI, clean-clone reproducibility test, git commit (none made; awaiting owner approval).
Acceptance criteria: separate frontend/backend - met; root and scoped instructions - met; no secrets committed - met (placeholders only, no commits exist); hello-world checks - met (tests/build/lint above); setup commands documented - met. Reproducibility from a clean checkout - NOT verified.
Known issues: Q14/Q7 open (Stage 0); Q23 warning.
Next action: owner decides on initial commit and clean-clone test; owner review/sign-off.
```

```text
Date: 2026-10-22
Stage: 1 (repository verification)
Status: DONE pending owner review (Stage 0 still IN PROGRESS)
Changes made: tracker only.
Commands actually run: git status -sb; git log; git remote -v; git branch -vv; git ls-remote origin; git ls-files filtered for .env/node_modules/.venv/dist/caches.
Results: branch main tracks origin/main (git@github.com:Vinay-Ampera/Sentinel-AI.git) at b55c582 "chore: initialize Sentinel AI project structure", the only commit; working tree clean; ls-remote returns the same hash; 44 tracked files, none are .env, node_modules, .venv, dist or tool caches.
NOT run: clean-clone reproducibility test (not yet done, still the one unverified Stage 1 criterion); CI (none configured).
Next action: owner approval for a clean-clone test; owner decisions on Q7 and Q14.
```

```text
Date: 2026-10-22
Stage: 0 (decisions) and 1 (clean-clone verification)
Status: Stage 0 DONE pending owner review; Stage 1 DONE pending owner review
Changes made: ADR-0001 -> Accepted with 2026-10-22 addendum (stack, scope, inputs, testing modes, MiroFish excluded, five requirements). OPEN_QUESTIONS: Q7 and Q14 resolved, Q18 note, decisions section and Stage 2 follow-ups. IMPLEMENTATION_PLAN: Stage 0/1 status and first-release scope. settings.json: supported_application_types, supported_inputs, testing_modes, exclusions, decisions_pending. Docs/config only; no application code changed.
Commands actually run: git clone git@github.com:Vinay-Ampera/Sentinel-AI.git into the session scratchpad (commit b55c582); backend: poetry install (in-project venv), pytest, ruff check, ruff format --check, mypy; frontend: npm ci, npm run lint, npm test, npm run build.
Test results (clean clone): pytest 1 passed, 1 warning (Q23); ruff clean; ruff format 8 files already formatted; mypy no issues in 4 files; npm ci 0 vulnerabilities; oxlint exit 0; vitest 1 file / 1 test passed; vite build succeeded.
NOT run: live uvicorn/dev-server request (command was denied by the permission prompt), Docker, CI. The clone verifies the committed state b55c582 only; the doc edits above are uncommitted.
Acceptance criteria (Stage 1): all met, including reproducible setup from a clean checkout (README commands for install, lint, test, build worked as written, with Poetry in-project venv for the backend).
Known issues: Q6/Q8 unvalidated; Q15-Q24 deferred; no CI; no live-server check.
Next action: owner reviews and commits these doc changes; sign-off on Stage 0/1; Stage 2 not started.
```

```text
Date: 2026-10-22
Stage: 2 — Architecture, data model, and API contracts
Status: DONE pending owner review; real-database apply NOT done
Changes made: Alembic env.py now reads DATABASE_URL from the environment only (psycopg 3). Added deps sqlalchemy>=2.0 and psycopg[binary]>=3.2 (poetry.lock updated). Migrations 0001_app_user_schema (roles, users, sessions, password_reset_tokens) and 0002_public_application_schema (24 tables: teams, memberships, projects, sources, target_authorizations, analysis_snapshots, plans, planned_tests, approvals, runs, batches, results, job_events, findings + events/evidence/verification/regression, artifacts, llm_usage, policies, audit_events, state_transitions) with DB-enforced rules (state machine, evidence-backed findings, append-only audit, production authorization guard, source URL guards). Tests: backend/tests/integration/test_migrations.py (8 tests, need disposable TEST_DATABASE_URL ending _test). Docs rewritten: DATABASE_SCHEMA, SYSTEM_ARCHITECTURE, API_DESIGN, JOB_AND_SANDBOX_DESIGN, SECURITY_AND_SAFETY, TEST_STRATEGY, FILE_STRUCTURE; new ADR-0002 (Proposed); backend .env.example/README/CLAUDE.md; OPEN_QUESTIONS Q25-Q30; settings.json.
Commands actually run: initdb + temporary PostgreSQL 17 server on a unix socket (/tmp/sai_pg, data in session scratchpad) with database sentinel_ai_test; poetry add; alembic upgrade head / downgrade base / upgrade head --sql; pytest (with and without TEST_DATABASE_URL); ruff check; ruff format --check; mypy; psql probes on the disposable DB only.
Results: upgrade head from empty DB succeeded; downgrade base succeeded; re-upgrade succeeded. pytest with TEST_DATABASE_URL: 9 passed (1 health + 8 DB tests), 1 upstream warning. Without it: 1 passed, 8 skipped. ruff check clean; ruff format clean (11 files); mypy no issues (4 files). Pre-existing tables/rows (public.legacy_probe) survived upgrade, downgrade and re-upgrade. Manual test: creating a conflicting public.teams table with a row then running upgrade failed with DuplicateTable, rolled back atomically (no app_user schema, no new tables) and left the row intact. Offline `upgrade head --sql` emits 29 CREATE TABLE statements. Missing DATABASE_URL gives a clear error.
NOT run: anything against the real sentinel-ai database (backend/.env is blocked from Claude by a deny rule and no credentials were available or requested; role "vinayrepalle" does not exist on the local server). Existing schemas/tables of sentinel-ai were therefore NOT inspected. No API endpoints, models, auth code, Docker, Redis, Celery, or frontend changes. Frontend checks not rerun (no frontend change). Nothing committed or pushed.
Acceptance criteria: DATABASE_SCHEMA agrees with API/workflow docs (cross-checked: entity/status names, source types, approval and production rules) - met by review, not by automated check; project ownership/access scope explicit (DATABASE_SCHEMA, SECURITY_AND_SAFETY) - met; migrations create the schema from an empty database - met on the disposable DB, not yet on the real DB; no feature depends on undocumented schema (deferred tables listed) - met.
Known issues: Q5/Q27 confirmation; Q25, Q26, Q28-Q30 new; retention/production store undecided; alerts/chat/report tables intentionally deferred; Argon2 dependency deferred to Stage 4.
Next action: owner inspects the real database and applies the migrations (commands in docs/DATABASE_SCHEMA.md), confirms ADR-0002, reviews and commits. Stage 3 not started.
```

```text
Date: 2026-10-22
Stage: 2 (finalization)
Status: DONE pending owner review; real-database apply still NOT done (by instruction)
Changes made: backend/.env.example rewritten with every Stage 2 variable, each labelled [NOW] (DATABASE_URL, TEST_DATABASE_URL) or [LATER: Stage N], placeholders only. backend/.env was not read or modified. Stage 2 status line unchanged.
Commands actually run: script comparing CREATE TABLE names in the two migrations with DATABASE_SCHEMA.md; restarted the disposable PostgreSQL 17 server (/tmp/sai_pg, database sentinel_ai_test) and stopped it afterwards; pytest with TEST_DATABASE_URL; ruff check; ruff format --check; mypy; alembic upgrade head and current on the disposable DB.
Results: 28 tables in migrations (4 app_user + 24 public), all named in DATABASE_SCHEMA.md; pytest 9 passed (1 upstream warning); ruff clean; format clean (11 files); mypy clean (4 files); alembic current = 0002_public_application_schema (head); information_schema shows app_user 4 tables, public 24 + alembic_version. .gitignore: .env.* ignored, .env.example not ignored and tracked.
NOT run: anything against the real sentinel-ai database; no new database created.
Acceptance criteria: all four met on the disposable database (see Stage 2 section). "Migrations create the schema from an empty database" is proven on the disposable DB only.
```

```text
Date: 2026-10-22
Stage: 2 (owner-reported real-database apply)
Status: Stage 2 DONE pending owner review
Report (from the project owner; NOT independently verified by Claude, who has no access to the real database): alembic migrations were applied to the existing local sentinel-ai database; 28 tables created (4 in app_user, 24 in public) and the owner's migration/verification commands completed successfully. Exact command output was not provided.
Claude's own evidence remains the disposable-database results above.
Next action: owner sign-off and commit. Stage 3 not started.
```

```text
Date: 2026-10-22
Stage: 3 — Local development services and configuration
Status: DONE pending owner review
Already present before the continuation (written in the interrupted session): dependencies pydantic-settings and redis; core/config.py (Settings, DatabaseSettings, ConfigError, value-free validation errors, production rules); core/logging.py (URL-password redaction); core/health.py (database, migration, redis probes returning status words only); db/engine.py (engine + session factory).
Newly implemented in the continuation: migrations/env.py now loads DATABASE_URL through DatabaseSettings (env, then backend/.env; SystemExit with a value-free message on error); core/errors.py (error envelope handlers); core/middleware.py (request ID + security headers); api/health.py (/health, /health/live, /health/ready, 200/503); main.py application factory create_app(settings) with lifespan, CORS allow-list, lazy engine (run with `uvicorn sentinel_ai.main:create_app --factory`); docker-compose.yml (Redis; optional separate PostgreSQL under profile local-db; no default passwords; ports bound to 127.0.0.1); root .env.example; backend/Makefile (lint, format-check, typecheck, test, check, migrate targets); backend/.env.example relabelled [NOW]/[LATER] with SENTINEL_ENV_FILE, DB_*, REDIS_*; tests: tests/unit/test_config.py, tests/unit/test_api_foundation.py, updated tests/unit/test_health.py, and 3 more tests in tests/integration/test_migrations.py (probes and /health/ready against the disposable DB); docs: backend README/CLAUDE.md, root README, FILE_STRUCTURE.
Commands actually run: pytest (with and without TEST_DATABASE_URL), make check, ruff check, ruff format --check, mypy, docker compose config (validation only), frontend npm run lint/test/build, temporary PostgreSQL 17 on a unix socket for the disposable database (stopped afterwards).
Results: with the disposable DB: pytest 36 passed (1 upstream warning); without it: 26 passed, 10 skipped (DB tests skip by design); ruff check clean; ruff format clean (21 files); mypy no issues (12 source files); `make check` passed end to end. Compose: `docker compose config` fails with a clear message when REDIS_PASSWORD is unset, validates with REDIS_PASSWORD only (services: redis) and with the local-db profile (redis, postgres). Frontend: lint exit 0, vitest 1 passed, build succeeded (unchanged code, rerun for completeness).
Acceptance criteria: (1) Services start from documented commands - Compose file and commands documented and config-validated; containers were NOT started (would pull images), so actual startup is not verified. (2) Secrets environment-supplied and not committed - met: SecretStr, no defaults for passwords, only .env.example files tracked, .env ignored. (3) Backend can connect to the database and run migrations - met on the disposable database (probes, upgrade/downgrade, /health/ready end to end); NOT run against the real sentinel-ai database by Claude. (4) Health/readiness work without exposing sensitive values - met (tests assert no user, password, host or database name in responses).
NOT run: uvicorn as a live server; docker compose up; anything against the real sentinel-ai database. Claude never connected to sentinel-ai in Stage 3, and ran no DDL/DML anywhere except the disposable database; the existing sentinel-ai tables were not touched (owner-reported state: 28 tables).
Owner-side verification (safe, read-only): cd backend && poetry run alembic current   # expect 0002_public_application_schema (head); then start the API and GET /api/v1/health/ready (expect database ok, migrations ok).
Known issues: Q31 below; Redis does not yet fail readiness (deliberate until Stage 7).
Next action: owner review/commit; Stage 4 not started.
```

```text
Date: 2026-10-22
Stage: 3 (final verification)
Status: DONE
Owner-reported live verification (project owner; Claude has no access to the real database or running servers and did not observe these): backend, frontend, the sentinel-ai database, Alembic migrations, and the health endpoints all work when run live. Redis is currently unavailable on the owner's machine; per the owner it will be addressed in Stage 7. Exact command output was not provided.
Claude-run checks (this session): with a disposable PostgreSQL database, `make check` passed: pytest 36 passed (1 upstream warning), ruff check clean, ruff format clean (21 files), mypy no issues (12 source files). Frontend: lint exit 0, vitest 1 passed, vite build succeeded. Disposable server stopped afterwards.
Decisions: Q31 resolved - Redis stays reported-but-not-required in /health/ready until Stage 7 (consistent with the owner's report: readiness is not blocked by the missing Redis). Q32 narrowed - Compose Redis/PostgreSQL services are config-validated only; actually starting them is deferred with Redis to Stage 7.
Acceptance criteria: (1) Services start from documented commands - met for backend, frontend and PostgreSQL (owner-reported); the Redis service is the documented exception, deferred to Stage 7 by owner decision. (2) Secrets environment-supplied and not committed - met. (3) Backend connects to the database and runs migrations - met (owner-reported live on sentinel-ai; Claude-verified on the disposable database). (4) Health/readiness without exposing sensitive values - met (tests; owner-reported live endpoints work).
NOT run by Claude: live servers, docker compose up, anything against sentinel-ai.
Next action: owner review/commit; Stage 4 not started.
```

