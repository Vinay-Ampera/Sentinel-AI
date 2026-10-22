# Sentinel AI — Full Project Blueprint

## 1. Project Overview

**Sentinel AI** is an agent-driven application quality platform that coordinates QA testing, security testing, AI/LLM testing, observability, accessibility checks, failure investigation, regression-test proposals, fix verification, and regression tracking.

The goal is to automate the *whole quality workflow*, not merely generate test cases or review code. Coding assistants such as Claude can perform many individual tasks when prompted; Sentinel AI aims to make those tasks repeatable, coordinated, evidence-based, and proactive with less manual prompting.

**Core workflow:** Discover → Plan → Review/Approve → Execute → Observe → Investigate → Propose Tests/Fixes → Verify → Track.

The technology stack and agent framework are intentionally undecided. They will be selected in a separate implementation plan.

## 2. Problem Statement

Testing and security work is often spread across separate tools, pipelines, logs, dashboards, and manual investigations. Developers must understand projects, choose checks, run tools, investigate failures, verify findings, create regression tests, and remember to rerun checks after fixes.

Sentinel AI should connect these activities in a transparent workflow, retain evidence, alert people when action is needed, and track whether problems are resolved or return.

## 3. Project Inputs

The platform should accept supported combinations of:
- Source-code repositories.
- Uploaded ZIP archives.
- Running application URLs.
- API specifications.
- Requirements and acceptance criteria.
- Existing test reports and coverage artifacts.
- Application logs, errors, and runtime traces.
- Relevant observability data from configured integrations.

The platform must clearly identify which inputs it received and inspected. It must not claim to have analyzed inaccessible files, logs, endpoints, or runtime behavior.

## 4. Supported Application Categories

The platform should adapt its test plan to the detected project type and available integrations.

### 4.1 Full-stack web applications
- UI journeys, end-to-end behavior, API integration, authentication, authorization, accessibility, and regression testing.

### 4.2 Backend applications and APIs
- Endpoint behavior, schema validation, positive/negative/boundary cases, authorization, integration failures, and API security.

### 4.3 AI/LLM applications
- Prompt injection, sensitive-data disclosure, output behavior, tool calls, retries, latency, token use, and estimated cost.

### 4.4 RAG systems
- Retrieval relevance, grounded answers, access-control enforcement, cross-user/tenant data leakage, indirect prompt injection, and missing-knowledge behavior.

### 4.5 Multi-agent systems
- Agent handoffs, tool permissions, loops, retries, timeouts, failed tool calls, and execution-trace completeness.

### 4.6 Cloud applications
- Approved checks for security-relevant configuration, identity permissions, exposed services, dependency risks, runtime health, and deployment regressions.

Not every check applies to every project. A capability matrix should record applicability, prerequisites, required permissions, available integrations, and limitations.

## 5. Main Product Capabilities

### 5.1 Project Analysis
Analyze the provided repository, archive, URL, API specification, or supporting artifacts to identify:
- Languages, frameworks, dependencies, and project structure.
- Likely application architecture and major components.
- Routes, endpoints, entry points, and trust boundaries where discoverable.
- Existing test files, frameworks, test commands, and coverage reports.
- Existing security, accessibility, and observability integrations.
- Potential testing gaps and unavailable information.

Clearly separate detected facts from inferred architecture.

### 5.2 Test Applicability and Coverage Gaps
Map components and requirements to existing tests and potential new checks. Identify untested modules, important flows with incomplete coverage, and checks blocked by missing data or permissions.

A missing test does not prove a defect. Coverage metrics must state what they measure—for example, lines, branches, endpoints, requirements, or components—and should not be reduced to a misleading single score.

### 5.3 Transparent Test Planning
Before execution, show:
- Test name, purpose, and reason it applies.
- Target files, components, endpoints, flows, or security boundaries.
- Category, priority, prerequisites, and required environment.
- Proposed inputs and expected behavior.
- Tool or test runner and expected evidence.
- Pass/fail criteria, limitations, and risk level.
- Whether human approval is required.

Users should be able to review, approve, reject, defer, or edit proposed tests where appropriate. The system must distinguish planned, approved, executed, skipped, blocked, and failed-to-start tests.

### 5.4 QA Test Generation and Execution
Coordinate established testing frameworks rather than rebuilding their functionality. Support relevant combinations of:
- Unit, integration, API, contract, and end-to-end tests.
- Requirement-based acceptance tests.
- Positive, negative, boundary, and error-handling tests.
- Regression tests and reliability checks.

Collect test output, reports, stack traces, and relevant artifacts. Distinguish passed, failed, skipped, blocked, and not-run results. Detect possible flaky tests without automatically blaming the application.

### 5.5 Web and API Security
Potential checks include:
- Authentication and authorization.
- Broken object-level or function-level access control.
- Inconsistent login errors and possible username enumeration.
- Timing differences that might reveal account validity.
- JWT validation, expiration, and privilege boundaries.
- Input validation, injection risks, unsafe output handling, and information disclosure.
- Insecure configuration and dependency vulnerabilities.

Security testing must be authorized and scoped. Destructive, state-changing, intrusive, or production-targeted checks require appropriate safeguards and explicit approval. A scanner alert is not automatically a confirmed vulnerability.

### 5.6 AI/LLM and Agent Security
Potential checks include:
- Direct and indirect prompt injection.
- System-prompt or sensitive-information disclosure.
- Cross-user or cross-tenant leakage in RAG.
- Unsafe tool calls and missing authorization.
- Excessive agent permissions.
- Unbounded loops, repeated calls, and uncontrolled retries.
- Unsafe treatment of external or retrieved content.
- Token-consumption spikes and cost-abuse scenarios.

Record relevant configurations and evidence. Because model behavior can be nondeterministic, a single run should not be treated as universal proof.

### 5.7 Observability and Proactive Alerts
Observability is a core capability. Where data and integrations are available, collect and correlate:
- Application logs, errors, and stack traces.
- Test output and test-run history.
- Request and service traces.
- Agent paths, handoffs, model calls, and tool calls.
- Retries, timeouts, and failures.
- Latency, token consumption, and estimated LLM costs.
- Relevant deployment or environment changes.

Detect meaningful events such as new or recurring errors, increased failure rates, timeouts, unusual latency, repeated agent calls, runaway workflows, and sudden token/cost increases.

Alerts should show severity, time, affected component, supporting evidence, confidence, and suggested next action. Thresholds should be configurable to reduce noise. Separate observed measurements from inferred causes. If instrumentation or log access is missing, disclose that limitation.

### 5.8 Failure-to-Test Feedback Loop
This is a key differentiator:
1. A log, trace, test run, or alert reveals a failure.
2. Sentinel AI alerts the developer or responsible team.
3. The investigation workflow correlates available logs, traces, source code, recent changes, and test results.
4. It presents likely causes with supporting evidence and uncertainty.
5. It proposes regression tests that could reproduce the behavior.
6. A developer reviews the proposed tests or changes when required.
7. Approved tests run in a controlled environment.
8. Sentinel AI records whether the failure reproduced and whether a fix resolved it.
9. The regression test is retained for future runs.

Not every log entry contains enough information to generate a valid test. When reproduction is not possible, the platform should explain what evidence or context is missing. Proposed code/configuration changes must remain proposals unless authorized; no silent production changes.

### 5.9 Failure Investigation
Correlate source code, stack traces, logs, traces, test results, and prior runs where available. Consider application defects, flaky tests, configuration problems, unavailable dependencies, and environment failures.

Classify investigation statements as:
- **Observed fact:** Directly supported by evidence.
- **Likely explanation:** Supported by evidence but not yet proven.
- **Unverified hypothesis:** Requires further investigation.
- **Confirmed cause:** Supported by strong verification or controlled reproduction.

Do not present a guess as a confirmed root cause.

### 5.10 Finding and Fix Verification
Where practical:
- Reproduce the reported behavior in a controlled environment.
- Run focused tests or security checks.
- Capture relevant evidence.
- Repeat checks where nondeterminism requires it.
- Rerun relevant tests after a fix.
- Check related behavior for regressions.

Possible finding states include new, investigating, suspected, confirmed, fix proposed, verification pending, verified resolved, reopened, and accepted risk. A code change or an AI claim alone is not proof that a fix worked.

### 5.11 Regression History
Retain an auditable history of plans, approvals, tests, tool/configuration versions, results, findings, alerts, evidence, proposed regression tests, fix-verification attempts, and reopened issues.

Compare runs to identify new failures, recurring issues, resolved findings, and regressions. Account for changes in test scope, environment, and tool versions when comparing results.

### 5.12 Accessibility Testing
Integrate relevant automated checks for accessible names and labels, keyboard navigation, focus behavior, color contrast, semantic structure, and applicable WCAG criteria.

Reports should include the criterion, affected page/element, evidence, severity, and suggested remediation. Explain that automated checks cannot identify every accessibility problem and that manual or assistive-technology testing may still be necessary.

### 5.13 LLM and Agent Observability
For supported applications and Sentinel AI workflows, track where available:
- Model configuration and calls.
- Prompt/response metadata under privacy controls.
- Token usage, estimated costs, latency, and errors.
- Agent handoffs, tool calls, retries, and termination reasons.
- Repeated calls, loops, and failed tool execution.
- Correlations with test results, alerts, and security findings.

Redact secrets and sensitive information, minimize retention, and enforce access controls.

### 5.14 Dashboard and Developer Interaction
The interface should present:
- Project inventory and analysis.
- Test plans and approvals.
- Live execution progress.
- Results and coverage gaps.
- Security findings and verification state.
- Observability alerts and correlated traces.
- Accessibility results.
- Investigations and proposed regression tests.
- Fix verification and run comparisons.
- Evidence-backed reports.

Users should be able to open the underlying evidence behind important results.

### 5.15 Evidence-Grounded Chatbot
Users may ask:
- Why did this test fail?
- Which components have no mapped tests?
- What evidence supports this vulnerability?
- Was the issue reproduced?
- Did the latest run verify the fix?
- Which errors increased after the last run?
- What evidence exists about prompt-injection protection?
- Which accessibility checks failed?
- Why did token usage increase?

Answers should cite or link to actual project files, test outputs, logs, traces, and findings where possible. If evidence is missing or inconclusive, the chatbot must say so rather than inventing results.

## 6. User Roles and Permissions

Sentinel AI will support three application roles. Exact permission details should be refined during implementation, but the separation of duties is part of the product requirements.

### 6.1 Developer
- View projects they own or are explicitly authorized to access.
- Inspect test plans, results, logs, traces, findings, and evidence.
- Select permitted test cases and categories, review plans, and start authorized test runs.
- Start, cancel, and rerun permitted test batches.
- Review, edit, and propose regression tests, subject to project policy.
- Choose which permitted checks run automatically when policy allows.
- Review investigation explanations and proposed changes.
- Inspect fix-verification results, relevant alerts, and reports.
- Cannot bypass platform security restrictions, override authorization scope, or test targets they are not authorized to assess.
- Cannot independently approve actions that policy reserves for an Admin or Super Admin.
### 6.2 Admin
- Manage project configuration and team access within their assigned scope.
- Configure testing policies, integrations, alert thresholds, and execution limits.
- Review and approve higher-risk tests where authorized.
- Manage project-level settings, test environments, and report access.
- Review activity and execution history for their scope.

### 6.3 Super Admin
- Manage platform-wide settings and administrative access.
- Manage or authorize tenant/team boundaries and global policies.
- Configure platform-wide integrations, security policies, retention rules, and execution safeguards.
- Audit privileged actions and system-wide activity.
- Control high-impact platform operations.

**Permission principle:** Super Admin privileges must not be granted implicitly to ordinary Admins. Enforce authorization in the backend, not only by hiding frontend controls. Apply least privilege, audit sensitive actions, and define project/team boundaries explicitly. Authentication method and detailed permission matrix remain implementation decisions.

## 7. Potential Agent Responsibilities

These are logical responsibilities, not a requirement to implement every item as a separate agent. Some tasks should be deterministic services or ordinary workflow steps.

### 7.1 Project Analysis Agent
Summarizes detected architecture, components, dependencies, likely trust boundaries, testing capabilities, and uncertainties.

### 7.2 Test Planning Agent
Recommends applicable tests based on requirements, architecture, coverage gaps, and risk; explains targets, prerequisites, evidence, and pass/fail criteria.

### 7.3 QA Execution Coordinator
Coordinates approved test plans, established test runners, execution state, and artifact collection. Actual tests should normally run through trusted tools and deterministic orchestration.

### 7.4 Security Testing Coordinator
Selects authorized checks, coordinates security tools, normalizes results, and identifies findings that need deeper verification.

### 7.5 AI/LLM Security Agent
Proposes relevant LLM/agent security scenarios and interprets outputs and traces with explicit uncertainty.

### 7.6 Observability and Anomaly Analysis Agent
Summarizes meaningful log and trace patterns, correlates events with tests, prioritizes alerts, and suggests investigation paths. Basic thresholds and counts should be deterministic where possible.

### 7.7 Failure Investigation Agent
Correlates source, logs, traces, and test outcomes; ranks plausible causes and recommends reproduction steps.

### 7.8 Regression Test Proposal Agent
Proposes tests for verified or reproducible failures, defines setup and expected behavior, and checks for overlap with existing tests.

### 7.9 Verification Agent
Coordinates or interprets verification attempts and distinguishes verified resolution from inconclusive results.

### 7.10 Reporting Agent
Produces summaries from validated records, links claims to evidence, and avoids overstating confidence.

### 7.11 Evidence-Grounded Assistant
Retrieves project records and artifacts to answer questions, explains uncertainty, and avoids unsupported claims.

Agents should be invoked conditionally. Use deterministic code for routing, permissions, thresholds, status transitions, and simple calculations. Use LLM reasoning when interpretation or synthesis adds value.

## 8. Agent Coordination and Workflow Safety

- Do not call every agent for every event.
- Keep agent inputs and outputs structured where possible.
- Record important decisions, tool calls, approvals, and outcomes.
- Bound retries, execution duration, concurrency, token usage, and costs.
- Support cancellation and safe failure handling.
- Prevent untrusted repository content, logs, and retrieved documents from changing policies or authorizing tool use.
- Isolate test execution from privileged platform services.
- Require approval for destructive tests, risky actions, production testing, or code changes as configured.
- Make the difference between a proposed action and an executed action explicit.

## 9. Evidence and Finding Quality

For important results, store the relevant identifiers, target, time, environment, tool version, test inputs (with sensitive data redacted), expected/actual behavior, supporting output, verification attempts, confidence, and limitations.

Suggested result categories:
- **Confirmed:** Strong direct evidence or controlled reproduction.
- **Likely:** Evidence supports the finding but verification is incomplete.
- **Unverified:** A tool or analysis raised a possibility that has not been validated.
- **Not reproduced:** The attempt did not trigger the issue under tested conditions; this does not prove the issue is absent.
- **Inconclusive:** Available evidence or environment limitations prevent a reliable conclusion.

## 10. Safety, Privacy, and Authorization

- Require explicit authorized scope and target environments.
- Separate read-only checks from state-changing or intrusive tests.
- Prefer isolated test environments.
- Require approval for risky or destructive actions.
- Avoid uncontrolled testing of public or production targets.
- Redact credentials, secrets, and personal data from artifacts where possible.
- Apply access controls and retention policies to logs, prompts, and traces.
- Audit approvals and privileged actions.
- Enforce time, cost, and resource limits.
- Fail safely when scope or authorization is unclear.

## 11. Reports and Outputs

Potential outputs include project analysis, proposed/approved test plans, execution reports, coverage-gap reports, security findings, observability alerts, accessibility reports, investigation summaries, proposed regression tests, fix-verification reports, and regression history.

All reports must distinguish planned, executed, skipped, blocked, and failed-to-start checks.

## 12. Success Measures

Evaluate the platform using measurable criteria:
- Detection precision and false-positive rate.
- Percentage of findings reproduced or verified.
- Useful coverage gaps identified.
- Requirement, endpoint, branch, or component coverage where measurable.
- Time from error detection to useful investigation.
- Time to create and validate a regression test.
- Percentage of proposed tests that reproduce the original failure.
- Fix-verification success rate.
- Regression detection rate.
- Alert usefulness and alert-noise rate.
- Accuracy of finding classifications.
- Agent calls, runtime, and estimated cost per completed workflow.
- Developer time saved compared with the existing process.

Establish baselines before claiming improvement.

## 13. Repository and Documentation Organization

Use one root directory with separate frontend and backend contexts. Keep source, tests, instructions, service-specific documentation, and container build definitions with the service they belong to. Keep shared architecture, decisions, and implementation tracking in `docs/`. This supports independent development and testing now and clearer containerized deployment later.

### Intended repository layout

```text
sentinel-ai/
├── .github/
│   └── workflows/                 # CI/CD workflows, added when useful
├── backend/
│   ├── src/                       # Backend application code
│   ├── tests/                     # Backend tests
│   ├── CLAUDE.md                  # Backend-specific Claude instructions
│   ├── Dockerfile                 # Production backend image
│   ├── Dockerfile.dev             # Development backend image
│   └── README.md                  # Backend setup, API endpoints, environment variables
├── frontend/
│   ├── src/                       # Frontend application code
│   ├── tests/                     # Frontend tests
│   ├── CLAUDE.md                  # Frontend-specific Claude instructions
│   ├── Dockerfile                 # Production frontend image (for example, static hosting)
│   ├── Dockerfile.dev             # Development frontend image
│   └── README.md                  # Components, build tools, setup, environment variables
├── docs/
│   ├── architecture/              # Detailed architecture documentation
│   ├── decisions/                 # Architecture/design decision records
│   ├── ARCHITECTURE.md            # Main architecture overview
│   ├── IMPLEMENTATION_PLAN.md     # Stage-by-stage tracker; frontend/backend separated
│   ├── SECURITY_AND_SAFETY.md     # Authorization, isolation, approvals, data protection
│   └── Sentinel_AI_Full_Project_Blueprint.md
├── docker-compose.yml             # Local multi-container development setup
├── docker-compose.prod.yml        # Production orchestration reference, hardened before use
├── CLAUDE.md                      # Root-wide Claude instructions
├── README.md                      # Master overview and quickstart
├── .gitignore
└── settings.json                  # Machine-readable project scope and constraints
```

This is the intended organization. Framework-specific source subfolders and exact container configurations should be decided in the implementation plan. Docker and Compose files are part of the planned repository structure, but their final contents must match the selected stack and deployment model; the production Compose file is a reference until security, secrets, networking, persistence, and operational requirements are reviewed.

### Documentation responsibilities
- **Root `CLAUDE.md`:** Overall purpose, project boundaries, shared conventions, security rules, documentation pointers, token-saving workflow, and when to read scoped instructions.
- **`frontend/CLAUDE.md`:** Frontend responsibilities, UI/UX and accessibility expectations, API integration, and frontend testing rules.
- **`backend/CLAUDE.md`:** Backend/API boundaries, authorization, evidence integrity, safe execution, sensitive-data handling, and backend testing rules.
- **Root `README.md`:** High-level overview, prerequisites, quickstart, and common commands.
- **`frontend/README.md`:** Frontend-specific setup, component organization, build/test commands, and environment variables.
- **`backend/README.md`:** Backend-specific setup, API overview, run/test commands, and environment variables.
- **`settings.json`:** Machine-readable scope and constraints, such as supported application categories, in-scope features, non-goals, approval requirements, and implementation status. Define its schema before relying on it; avoid duplicating every Markdown instruction.
- **`docs/IMPLEMENTATION_PLAN.md`:** Stage-by-stage tracker with frontend, backend, shared integration, documentation, and deployment work tracked separately, including dependencies, acceptance criteria, tests, and status.
- **`docs/ARCHITECTURE.md` and `docs/architecture/`:** Main architecture overview and supporting diagrams/details as decisions are made.
- **`docs/decisions/`:** Important design decisions and their rationale.
- **`docs/SECURITY_AND_SAFETY.md`:** Authorization, sandboxing, approvals, sensitive-data handling, and safe execution expectations.
- **`.github/workflows/`:** Add CI workflows when the repository and selected toolchain are ready.

Keep instructions concise and non-duplicative. Update documentation when a decision changes. Create only files with a clear purpose, and do not treat placeholder Docker/CI files as working configurations before they have been implemented and validated.

## 14. Claude Workflow, Skills, and Token Efficiency

Claude should be guided by repository instructions and task-specific context rather than receiving the entire blueprint for every small change.

### Working rules
- Read root instructions first; read frontend/backend instructions only for the relevant area.
- Consult the implementation tracker and relevant architecture/security notes before making substantial changes.
- Work on one clearly scoped task at a time and follow its acceptance criteria.
- Inspect existing code before editing; preserve unrelated functionality.
- Report changed files, decisions, tests actually run, tests not run, and blockers.
- Do not claim a test passed unless its result was observed.
- Keep plans and documentation concise; link to detailed references instead of copying them.
- Avoid repeatedly reading the entire blueprint when a small relevant section is sufficient.
- Prefer deterministic scripts and existing tools for routine checks.
- Ask the user to run small, low-risk commands locally when that is simpler and saves model/tool usage; clearly state the command and expected result.
- Never ask the user to run destructive or security-sensitive commands without explaining their effect and confirming scope.
- Do not let token-saving shortcuts skip security, authorization, or required verification.

### Skills and tools
Potential skills and tools mentioned for evaluation include:
- **UI/UX and accessibility design skill:** Useful for dashboard usability, accessible interaction, and consistent visual design.
- **Superpowers:** Consider for structured software-development workflows when available and relevant.
- **Graphify:** Consider if it provides useful codebase or dependency-graph understanding for this repository.
- **OmniRoute / NVIDIA-related tooling:** Evaluate only if a concrete model-routing, inference, or integration requirement justifies it.
- **Other skill Markdown files:** Add task-specific instructions only when they offer a clear benefit.

Names, availability, installation, and compatibility must be verified before use. These are candidates, not mandatory dependencies. Do not install or invoke every tool simply because it was mentioned. “Ponytail” was mentioned as a possible skill/tool name; its intended product and value should be clarified before including it as a requirement.

## 15. Implementation Plan Expectations

A separate implementation plan will be created before coding. It should:
- Begin with repository/environment setup and clear instructions for a first-time Claude user.
- Create the root, frontend, backend, and documentation structure correctly.
- Establish root and scoped `CLAUDE.md` instructions and `settings.json`.
- Track frontend, backend, shared integration, and documentation work separately.
- Define stage prerequisites, deliverables, acceptance criteria, and verification.
- Identify which commands Claude should run and which small commands the user can run manually.
- Keep Docker and deployment preparation in scope for later stages, without prematurely fixing the final deployment design.
- Record unresolved choices rather than silently assuming a stack or framework.

Do not start implementation merely from this blueprint. Agree on the initial scope and technology decisions in the implementation-planning discussion first.

## 16. Scope Boundaries and Non-Goals

Sentinel AI is not intended to:
- Replace established test runners, security scanners, observability systems, or accessibility tools without a strong reason.
- Generate tests and claim they passed without executing them.
- Treat every scanner alert or model suspicion as a confirmed vulnerability.
- Guarantee complete security, coverage, or accessibility.
- Automatically change production code or infrastructure without authorization.
- Run every available check regardless of relevance, risk, or cost.
- Use an LLM for tasks deterministic code can handle more reliably.
- Assume every log error contains enough information for a reproducible test.
- Replace developer judgment for high-impact decisions.

The differentiator is the coordinated, continuous, evidence-driven workflow: understand, plan, execute, observe, investigate, propose, verify, and track.

## 17. Open Decisions for Later

The following remain undecided:
- Initial release scope and first supported application categories.
- Technology stack and frontend/backend frameworks.
- Agent framework and orchestration model.
- Model providers and routing.
- Data storage for projects, runs, findings, evidence, and traces.
- Repository access and sandboxing.
- Execution environment and isolation strategy.
- Authentication and detailed role-permission matrix.
- Team/tenant boundaries.
- Observability integrations and retention.
- Alert thresholds and risk classification.
- Test selection and prioritization.
- Evidence schema and finding lifecycle.
- CI/CD integration.
- Deployment model and Docker details.
- Which optional skills and external tools are genuinely useful.

## 18. Summary

**Sentinel AI is an evidence-driven application quality platform that coordinates QA, security, AI/agent testing, observability, accessibility, failure investigation, regression-test proposals, fix verification, and history.**

Its defining loop is:

**Detect → Gather evidence → Investigate → Propose tests/changes → Approve when needed → Execute safely → Verify → Track regressions.**

The platform should help developers act on real failures, show exactly what has and has not been tested, and maintain reliable evidence. This blueprint defines the desired product; the implementation plan will define how to build it.
