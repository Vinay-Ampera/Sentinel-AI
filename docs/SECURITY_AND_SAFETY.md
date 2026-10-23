# Security and Safety

> Status: **Stage 6 implemented** (plan approval policy, target authorization, production block; see "Plans, approvals and target gating"). **Stage 4 implemented** for authentication, sessions, CSRF, lockout, the role matrix and user administration (ADR-0002, Accepted). Project-scoped and approval rules are enforced by `require_project_access` and `core/permissions.py` as those routes are built. The sandbox threat model is still required before untrusted code runs (Q6, Stage 8).

## Roles and permission matrix
Roles live in `app_user.roles` (one role per user). Project access is separate and per-project (`read` < `run` < `manage`) via ownership, `project_memberships`, or team access. **Role grants capabilities; project access grants scope. Both must allow an action.**

| Action | Developer | Admin | Super Admin |
|---|---|---|---|
| Sign in, change own password, manage own sessions | ✔ | ✔ | ✔ |
| Create project (becomes owner), register sources | ✔ | ✔ | ✔ |
| View project/plans/runs/results/logs/findings/artifacts | projects with an explicit grant | projects with an explicit grant | projects with an explicit grant, or a temporary break-glass grant (read only) |
| Create plans (any mode), start/cancel/rerun **approved** runs | `run` level | `run` level | all |
| Approve a plan (any risk) | if a project manager or designated approver, not the requester | same | same |
| …high/critical risk additionally | ✘ (org policy: role never approves) | ✔ if the above holds | ✔ if the above holds |
| Approve remote dev/staging target authorization | ✘ | ✔ with project management access or designation, not requester | same |
| Enable/approve **production** testing | ✘ | ✘ | ✔ only when global policy `production_testing.allowed = true`, four-eyes, time-boxed, justified |
| Attach evidence, triage findings, propose regression tests | `run` level | ✔ | ✔ |
| Mark finding `accepted_risk` / `false_positive` | ✘ | ✔ | ✔ |
| Manage project members/teams | `manage` level on own project | ✔ in scope | ✔ |
| Create/deactivate users, reset passwords | ✘ | developers only | ✔ |
| Grant/revoke Admin; create Super Admin | ✘ | ✘ | ✔ (cannot remove last Super Admin) |
| Change project policy (allowed risk levels, approval levels, approvers) | ✔ with `manage` on the project (any role) | same | same |
| Change organization policy (allowed levels, high-risk roles, production flag, LLM limits) | ✘ | ✘ | ✔ |
| Read audit log | own actions only | scope | all |
| Break-glass: temporary read-only access to one project (incident response) | ✘ | ✘ | ✔ (justified, ≤ 4 h, audited, revocable by the project manager) |
| Bypass sandbox, scope, approval, or policy | **never — for any role** | | |

Admin and Super Admin are also project users: their extra capabilities (user administration, organization policy, being an *eligible role* for high-risk approval) do **not** give access to any project's plans, runs, results or logs. They need an explicit grant like anyone else (owner, membership or team access), and an unknown or ungranted project is a 404.

## Authentication and sessions (ADR-0002, implemented in Stage 4)
- Email + password; passwords hashed with **Argon2id** (`password_hash` stores the encoded string; minimum 12 chars; built-in common-password list only, a breach corpus is Q33); no password is ever logged.
- Server-side sessions: random 256-bit token in an `HttpOnly; Secure; SameSite=Lax` cookie; only a keyed hash (HMAC with `SESSION_TOKEN_PEPPER`) is stored in `app_user.sessions`. Idle timeout (default 30 min) and absolute timeout (default 12 h); logout and password change revoke sessions; token rotated on login.
- CSRF: per-session token (hash stored) required in `X-CSRF-Token` for state-changing requests, plus `SameSite` cookies and Origin checking.
- Brute-force controls: per-account failure counter + `locked_until`, per-IP rate limits, uniform error messages (no account enumeration), audit of failures.
- First Super Admin is bootstrapped by a local management command run by the operator (password from a prompt/secret store, never from a committed file). SSO/OAuth is out of scope for the first release (Q5).

## Authorization rules
- Enforced on API endpoints **and re-checked in workers** immediately before execution. Frontend checks are UX only.
- Every child entity is authorized through `project_id`; IDs alone never grant access. Unauthorized lookups return `404`.
- Policies in `public.policies` (global then project override, project may only be stricter for safety keys) gate risk approval, production testing, and LLM budgets.
- LLM output never bypasses authorization, approval, or sandbox policy; it is parsed into validated structures and re-evaluated by deterministic code.

## Plans, approvals and target gating (Stage 6, implemented; revised in the access review)
- **Responsibility.** The user who runs tests on a project is responsible for them. An approval is requested from people with an explicit grant on *that project*, never from a person because of their role, and never from the requester.
- **Who approves (`services/policy.py`).** Eligible = explicit project grant AND not the requester AND (high/critical only) a role the organization allows (`high_risk_approver_roles`, default Admin/Super Admin; Developers only if a Super Admin explicitly adds `developer` at organization level) AND either the project's designated approvers for that level (`risk_approvers`, chosen by the project manager from active project members) or, when none are designated, project managers (`manage` access: the owner and whoever they gave it to). The requester can only withdraw (reject) their own pending plan.
- **Who controls risk for a project.** Anyone with `manage` on the project (the owner by default, any role) sets, within organization bounds: `allowed_risk_levels` (checks above it are `blocked`), `approval_required_risk_levels` (can only add to the always-approved high/critical floor) and `risk_approvers`. Organization policy (Super Admin) sets the outer bounds; effective values are the intersection/union that is stricter. A project can never enable production.
- **What the levels mean (`RISK_DEFINITIONS`).** low: reads source or sends passive read-only traffic to a local target; no egress, no changes. medium: needs outbound network, drives a UI or probes an AI endpoint on a local target, or sends any traffic to a shared remote environment. high: intrusive, attack-style, load-generating or developer-supplied code, or an active check on a shared remote environment. critical: reserved for destructive or production-affecting work (no catalog check is critical). Risk comes from code in the catalog, never from a prompt, developer or model; a unit test enforces the rules (active/egress checks are never low; always-approval checks are high+).
- **Break-glass (`services/break_glass.py`).** A Super Admin may open one project read-only for at most 4 hours with a written justification (≥ 20 chars). It never allows run, manage, policy edits or any approval decision, is not a membership (so it cannot make someone a designated approver), ends by the database clock or on revocation by the grantee or a project manager, cannot be extended (a new grant is a new audited row), and requires the user to still be a Super Admin. Audited: `breakglass.grant`, `breakglass.access` for every request served only because of it, `breakglass.revoke`; project managers can list grants (`GET /projects/{id}/break-glass`).
- **Decisions need an explicit grant.** Approvals, including production authorization, use explicit access only; a Super Admin must already be a project member (read is enough) to approve production.
- Plans are built only from the deterministic check catalog (`services/check_catalog.py`); prompts and developers select entries and give a few validated parameters, never commands. Prompt text is data.
- A submitted plan is frozen (API + DB triggers), bound to a SHA-256 of the reviewed content, and approvable only while it still matches. Decisions are final and audited (`plan.submit`, `plan.auto_approved`, `approval.decision`, `approval.denied`, `policy.update`).
- Remote development/staging URLs are blocked until an approved, unexpired authorization covers the check's risk, path prefix and (for active checks) a mutating method; deciding it additionally needs the organization-reserved Admin capability plus the eligibility above. Hosts are fixed by the source.
- **Production**: blocked by default (organization policy `production_testing.allowed=false`; a project cannot enable it). Even when enabled: Super Admin only, with a project grant, not the requester, written reason ≥ 10 chars, window ≤ 24 h. Production remote sources cannot be registered through the API (Stage 5).
- **Runs, results and logs (Stage 7+).** Every route that returns a run, result, event or log must authorize through the owning project's grant (`authorize_project` / `require_project_access`); there is no role bypass and no "list all" for any role.
- Localhost sources are loopback-only and need no authorization; sandbox reach is Q26.

## Production and target safety
- **Production testing is blocked by default** (seeded policy `production_testing = {"allowed": false}`). Even when allowed, it needs an approved `target_authorizations` row for that source: time-boxed (`valid_until`), written justification, scope (hosts/paths/methods/risk levels), decided by someone other than the requester, Super Admin only. Expired/revoked authorizations block runs immediately.
- Dev/staging URLs need an approved authorization before any non-passive check; localhost URLs are limited to loopback hosts (database CHECK).
- Only the authorized scope may be contacted; a scan that would leave scope is aborted. No public-target scanning, no destructive actions without approval, no denial-of-service style tests.
- Dev/staging targets must not be assumed non-sensitive: treat their data as confidential, avoid storing response bodies beyond what evidence requires, and redact.

## Secrets and data handling
- Secrets: only in untracked local env files or a secret store; `.env.example` holds names and placeholders. Never in source, committed settings, frontend env vars (`VITE_*` is public), logs, prompts, artifacts, or test output.
- Logs/prompts/artifacts are redacted (known secret patterns, configured values, `Authorization`/cookie headers) before storage or sending to Gemini; only the minimum necessary context is sent to the model.
- Sandboxes receive no platform secrets; project-specific secrets, if ever needed, are scoped, short-lived, and Stage 8+ design.
- `password_hash`, token hashes, and internal storage keys never appear in API responses.

## Evidence storage and integrity
Artifact bytes live outside Postgres via the store interface (non-guessable keys derived from IDs, not user filenames; path traversal rejected at DB and app layers). Each artifact records SHA-256, size, content type; downloads are authorized, audited, `attachment` + `nosniff`. ZIP/uploads are validated and extracted only in a sandbox. Retention in DATABASE_SCHEMA. Findings need stored evidence to be `confirmed`.

## Audit
`audit_events` (append-only, DB-enforced) records: login success/failure/lockout, logout, password/role/policy changes, user creation/deactivation, project membership changes, source and authorization requests/decisions, approvals, run start/cancel/rerun, artifact download, permission denials, LLM budget blocks. Fields: actor, action, target, project, outcome, request ID, IP, redacted detail.

## Threat considerations (initial; full model before Stage 8)
Prompt injection from repo/ZIP/web content (treated as data; no tool authority from model text) · malicious ZIP (traversal, symlink, bomb) · hostile project code escaping the sandbox (isolation level TBD) · SSRF via URL sources (loopback-only for localhost, allow-listed hosts for remote, block metadata/internal ranges) · credential theft via logs/artifacts (redaction, no secrets in sandbox) · privilege escalation via role/membership edits (Super Admin-only for Admin grants, last-admin guard, audited) · cross-project data access (project-scoped queries + mandatory tests) · session theft/CSRF (cookie flags, CSRF token, short idle timeout) · LLM cost abuse (budgets, rate limits).

## Rules (unchanged)
Never fabricate results; scanner output is not "confirmed" without verification evidence; "not run" must be reported as such.
