# Security and Safety

> Status: **Stage 4 implemented** for authentication, sessions, CSRF, lockout, the role matrix and user administration (ADR-0002, Accepted). Project-scoped and approval rules are enforced by `require_project_access` and `core/permissions.py` as those routes are built. The sandbox threat model is still required before untrusted code runs (Q6, Stage 8).

## Roles and permission matrix
Roles live in `app_user.roles` (one role per user). Project access is separate and per-project (`read` < `run` < `manage`) via ownership, `project_memberships`, or team access. **Role grants capabilities; project access grants scope. Both must allow an action.**

| Action | Developer | Admin | Super Admin |
|---|---|---|---|
| Sign in, change own password, manage own sessions | ✔ | ✔ | ✔ |
| Create project (becomes owner), register sources | ✔ | ✔ | ✔ |
| View project/plans/runs/findings/artifacts | own/shared projects | projects in admin scope | all (audited) |
| Create plans (any mode), start/cancel/rerun **approved** runs | `run` level | `run` level | all |
| Approve low/medium-risk plans/tests | only if policy delegates | ✔ in scope | ✔ |
| Approve high/critical-risk, destructive, intrusive tests | ✘ | ✔ in scope (not own request) | ✔ (not own request) |
| Approve remote dev/staging target authorization | ✘ | ✔ in scope | ✔ |
| Enable/approve **production** testing | ✘ | ✘ | ✔ only when global policy `production_testing.allowed = true`, four-eyes, time-boxed, justified |
| Attach evidence, triage findings, propose regression tests | `run` level | ✔ | ✔ |
| Mark finding `accepted_risk` / `false_positive` | ✘ | ✔ | ✔ |
| Manage project members/teams | `manage` level on own project | ✔ in scope | ✔ |
| Create/deactivate users, reset passwords | ✘ | developers only | ✔ |
| Grant/revoke Admin; create Super Admin | ✘ | ✘ | ✔ (cannot remove last Super Admin) |
| Change policies (approval levels, LLM limits, production flag) | ✘ | project-scope, cannot enable production | ✔ |
| Read audit log | own actions only | scope | all |
| Bypass sandbox, scope, approval, or policy | **never — for any role** | | |

"Admin scope" = projects the Admin owns, teams they own, and projects/teams explicitly delegated to them; the exact delegation model is a Stage 4 detail but the default is **no implicit global access for Admin**.

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
