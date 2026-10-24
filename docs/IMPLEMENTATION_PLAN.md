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
│   ├── PROJECT_TRACKER.md
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

- `docs/IMPLEMENTATION_PLAN.md`: Stage list with status, next action, requirements and acceptance criteria.
- `docs/PROJECT_TRACKER.md`: Detailed progress, completed features, changed files, test results, decisions, and remaining work.
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

**Status values:** `Pending`, `Ongoing`, `Completed`.

This section lists only each stage's status, next action, requirements and acceptance criteria. Evidence, dates, changed files, test results, decisions and remaining work are in [`PROJECT_TRACKER.md`](PROJECT_TRACKER.md). Do not mark a stage Completed until its acceptance criteria are met and recorded there.

### Stage 0 — Confirm scope and decisions
**Status:** Completed  
**Next action:** None.

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
**Status:** Completed  
**Next action:** None.

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
**Status:** Completed  
**Next action:** None (owner reports migrations applied to the real database; see tracker).

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
**Status:** Completed  
**Next action:** Start Redis with Stage 7 (Q32).

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
**Status:** Completed  
**Next action:** Owner review and commit. Membership/approval audit rows continue in Stage 6.

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
**Status:** Completed  
**Next action:** Owner review and commit. Analysis of Git, localhost and remote sources waits for Stages 6 and 8 (Q36).

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
**Status:** Completed  
**Next action:** Owner review and commit; apply migration 0003 to the real database (`alembic upgrade head`). Stage 7 not started. Criterion 4 (plan linked to a run) is enforced in the schema; run creation itself is Stage 7.

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
**Status:** Completed  
**Next action:** Owner review and commit; apply migrations 0003, 0004 and 0005 to the real database (`alembic upgrade head`, review the SQL first); start Redis (`docker compose up -d redis`) and run `make worker` / `make beat`. Stage 8 not started. Evidence: PROJECT_TRACKER section 7 (2026-10-23, Stage 7).

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
**Status:** Completed  
**Next action:** Owner review and commit; build the runner image (`make -C backend sandbox-image`); apply migrations 0003-0005 to the real database after review (Stage 8 adds none). Enable only deliberately with `JOB_EXECUTOR=docker`. Stage 9 not started. Evidence: PROJECT_TRACKER section 7 (2026-10-23, Stage 8) and `docs/architecture/SANDBOX_THREAT_MODEL.md`.

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
**Status:** Completed  
**Next action:** Owner review and commit; run `make -C backend sandbox-image` (now vendors pytest from the lock file); apply migrations 0003-0006 to the real database after review; decide on enabling `SANDBOX_ALLOW_PROJECT_CODE` per deployment (read the threat model first). Playwright was not started (needs browser sandboxing, Q69). Stage 10 not started. Evidence: PROJECT_TRACKER section 7 (2026-10-24, Stage 9).

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
**Status:** Completed (Bandit and the dependency audit verified; Semgrep and ZAP integrated but NOT verified against the real tools: Q73, Q75)  
**Next action:** Owner review and commit; `make -C backend advisories` (connected machine), `make -C backend sandbox-image`; apply migrations 0003-0008 to the real database after review. Before relying on Semgrep: `make -C backend scanner-image SEMGREP_VERSION=<pin>`, `semgrep --validate --config sandbox/semgrep-rules`, one real scan. Before enabling ZAP: the network and verification checklists in SANDBOX_THREAT_MODEL.md. Stage 11 not started. Evidence: PROJECT_TRACKER section 7 (2026-10-24 Stage 10; 2026-10-23 Stage 10 completion), ADR-0007, ADR-0008.

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
**Status:** Completed with the fake provider (all five graphs, the gateway, redaction and evidence filtering are built and tested; one owner-approved real planning request succeeded; other prompts, timeouts and quality are unverified: Q110, Q111, Q115)  
**Next action:** Owner review and commit (nothing is committed). Apply migrations 0003-0009 to the real database after reviewing them (0009 is written and tested on a disposable database only). Set the real prices for the configured `GEMINI_MODEL` (the one smoke request used placeholders) (`LLM_PRICE_*`) before relying on cost figures. Stage 12 not started. Evidence: PROJECT_TRACKER section 7 (2026-10-24 Stage 11 entries), ADR-0010 (with the Step 2-8 amendments), `architecture/AGENT_WORKFLOWS.md`.

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
**Status:** Completed (all eight steps built and tested with the fake provider and a disposable database; thresholds, fingerprint grouping and draft eligibility are unmeasured on real telemetry: Q128, Q130, Q133; the new screens were not opened in a real browser: Q140)  
**Next action:** Owner review and commit (nothing is committed). Q123 and Q142 are approved (ADR-0002 amended). Review migrations 0003-0010 using DATABASE_SCHEMA "Pre-apply review" and apply them yourself (never automatic; Q141). Paste the new settings from PROJECT_TRACKER into `backend/.env.example` (Claude cannot edit it). Operators must schedule `cli purge-events` and `cli evaluate-alerts` themselves (Q125, Q70). Stage 13 not started. Evidence: PROJECT_TRACKER section 7 (Stage 12 entries), ADR-0011 (with the implementation amendments), SECURITY_AND_SAFETY "Observability and alerts".

**Steps** (all done 2026-10-24): 1 design + ADR-0011 · 2 event model and ingestion (migration 0010, ingest keys, redaction, caps) · 3 deterministic detection and thresholds · 4 correlation and internal failure sources · 5 alert API, acknowledgement, audit · 6 failure-to-test loop (alert subject for the investigation and regression graphs) · 7 frontend Alerts tab · 8 final checks and security review.

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
**Status:** Pending  
**Next action:** Starts after Stage 12.

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
**Status:** Pending  
**Next action:** Starts after Stage 13.

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
**Status:** Pending  
**Next action:** Starts after Stage 14.

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
**Status:** Pending  
**Next action:** Starts after Stage 15.

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

## 16b. Frontend Track (separate from the stage list)

Owner decision 2026-10-23: the full frontend is built in its own phases F0-F9, tracked apart from Stages 0-16. Stage 11 was paused during F0-F9; it has since been built, and its screens (the Assistant and Proposals project tabs and the finding actions) were added afterwards on the owner's request (PROJECT_TRACKER section 7, 2026-10-24). UI rules: [`architecture/ui-ux-design.md`](architecture/ui-ux-design.md) (top navbar only, no sidebar; Light/Dark/System themes; system font stack; WCAG 2.2 AA practices). Decisions: [ADR-0009](decisions/ADR-0009-frontend-foundation.md). Evidence per phase: PROJECT_TRACKER section 7. Each phase starts only after the owner approves the previous one.

| Phase | Scope | Status | Next action |
|---|---|---|---|
| F0 | Foundation: design tokens, themes, router, navbar shell, shared components, status vocabulary, a11y test harness | Completed (owner approved by starting F1, 2026-10-23) | None. |
| F1 | Public homepage, sign-in page, informational Request Access page | Ongoing (implemented and checked; awaiting owner review) | Owner browser review (checklist in PROJECT_TRACKER). |
| F2 | Auth and account (sign-in flow, route protection, session expiry, password, sessions) | Ongoing (implemented and checked; awaiting owner review) | Owner browser review. |
| F3 | Projects, overview (composed from existing endpoints), setup (sources, members), analysis | Ongoing (implemented and checked; awaiting owner review) | Owner browser review. |
| F4 | Test plans and approvals | Ongoing (implemented and checked; awaiting owner review) | Owner browser review. |
| F5 | Runs, results, evidence: run history and start, test execution report, result detail with cases and evidence (designed from ui-ux-design.md; the owner's screenshot was never available) | Ongoing (implemented and checked; awaiting owner review) | Owner browser review (checklist in PROJECT_TRACKER). |
| F6 | Security findings (filters, summary, table, detail, review, linked duplicates) | Ongoing (implemented and checked; awaiting owner review) | Owner browser review. |
| F7 | Governance (authorizations, policy, break-glass) and admin (users, organization policy) | Ongoing (implemented and checked; awaiting owner review) | Owner browser review. |
| F8 | Roadmap page: clearly labelled planned features (Stages 11-16), read-only | Ongoing (implemented and checked; awaiting owner review) | Owner browser review. |
| F9 | Accessibility, responsive and documentation hardening | Ongoing (axe checks on the main pages and fixes done; visual and manual checks by the owner still needed) | Owner manual pass (checklist in PROJECT_TRACKER). |

**F0 acceptance criteria:** light/dark/system themes persist and do not flash; responsive top navbar with keyboard operation and no sidebar; shared components handle loading, error, empty and permission-denied states; one status vocabulary that never relies on colour alone; existing plans/runs/findings panels still work; lint, tests and build pass.

## 17. Progress Tracking

Progress updates (dates, commands run, test results, changed files, decisions, remaining work) are recorded in [`PROJECT_TRACKER.md`](PROJECT_TRACKER.md), which also holds the update template. Keep one current status per stage here; use Git history and `docs/decisions/` for historical detail.

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

Moved to [`PROJECT_TRACKER.md`](PROJECT_TRACKER.md) (section "Progress log").
