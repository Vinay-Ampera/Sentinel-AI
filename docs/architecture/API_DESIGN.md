# API Design

> Status: **Stage 2 contract (design only; nothing implemented).** Request/response bodies are specified in field lists; exact Pydantic schemas are written when each endpoint is implemented and must match this document. FastAPI generates OpenAPI from them.

## Conventions
- Base path `/api/v1`. JSON only (`application/json`), except artifact download and ZIP upload (`multipart/form-data`). IDs are UUID strings; timestamps are RFC 3339 UTC.
- **Auth:** opaque session cookie (`HttpOnly`, `Secure` outside local dev, `SameSite=Lax`) set by `POST /auth/login`. State-changing requests (POST/PUT/PATCH/DELETE) also require header `X-CSRF-Token` (value returned by login / `GET /auth/me`). See ADR-0002. No bearer tokens in the first release.
- **Authorization:** every protected route resolves the caller, then checks (role, project access level, resource state, policy) server-side. Unknown or inaccessible resources both return `404` (no existence leak); role-insufficient on a known-accessible resource returns `403`.
- **Pagination:** `?limit=` (1–100, default 25) and `?cursor=` (opaque). Response: `{"items": [...], "next_cursor": "..."|null}`. Default sort newest first.
- **Idempotency:** `POST /projects/{id}/test-runs` accepts header `Idempotency-Key` (8–128 chars); the same key returns the original run.
- **Long work is asynchronous:** endpoints return `202 Accepted` with the resource; clients poll `GET` (no SSE/WebSocket initially).
- **Request IDs:** server returns `X-Request-ID` on every response; it appears in logs, audit rows and error bodies.
- **Rate limiting:** login and expensive endpoints (plan generation, uploads) are rate limited per user/IP; `429` with `Retry-After`.
- **Validation:** unknown fields rejected; string lengths bounded; URLs validated (scheme http/https/git, no embedded credentials); never accept shell command strings as input.

## Error envelope
All errors:
```json
{ "error": { "code": "validation_failed", "message": "Human-readable summary",
  "details": [{"field": "target_url", "issue": "must be localhost"}],
  "request_id": "req_01H..." } }
```
| HTTP | `code` | When |
|---|---|---|
| 400 | `bad_request` | Malformed request |
| 401 | `unauthenticated` | Missing/expired/revoked session |
| 403 | `forbidden`, `csrf_failed`, `approval_required`, `policy_blocked` | Authenticated but not allowed; plan/test needs approval; policy (e.g., production) blocks |
| 404 | `not_found` | Missing **or inaccessible** |
| 409 | `conflict`, `invalid_state_transition`, `already_exists` | State machine or uniqueness violation |
| 413 | `payload_too_large` | Upload over limit |
| 415 | `unsupported_media_type` | Disallowed upload type |
| 422 | `validation_failed` | Field validation (details populated) |
| 429 | `rate_limited`, `budget_exceeded` | Rate or LLM budget exceeded |
| 500/503 | `internal_error`, `dependency_unavailable` | No internal detail or secrets in `message` |

## Roles
`D` = Developer, `A` = Admin, `S` = Super Admin. "Project level" = minimum project access (`read` < `run` < `manage`, Developers via ownership/membership/team; Admin/Super Admin per scope in DATABASE_SCHEMA). Full matrix in SECURITY_AND_SAFETY.

## Endpoints

### Auth and identity
| Method & path | Purpose | Who |
|---|---|---|
| `POST /auth/login` `{email,password}` → `200 {user, csrf_token}` + cookie | Sign in; throttled; lockout after repeated failures; audit | public |
| `POST /auth/logout` | Revoke current session | any signed-in |
| `GET /auth/me` → `{user{id,email,display_name,role}, csrf_token}` | Current identity | any signed-in |
| `POST /auth/password` `{current,new}` | Change password; revokes other sessions | any signed-in |
| `GET /auth/sessions`, `DELETE /auth/sessions/{id}` | Own sessions list/revoke | any signed-in |

### Users and administration (`/users`, `/admin`)
| Method & path | Purpose | Who |
|---|---|---|
| `GET /users` `?q=` | List users (limited fields; Developers see only members of shared teams/projects) | D(limited) A S |
| `POST /admin/users` `{email,display_name,role,temp_password?}` | Create user (never `super_admin` unless caller is S) | A (developer role only) S |
| `PATCH /admin/users/{id}` `{display_name?,is_active?,role?}` | Update/deactivate; role changes to/from `admin`/`super_admin` only by S; cannot demote/deactivate last S | A (limited) S |
| `POST /admin/users/{id}/reset-password` | Issue reset token (delivered out of band) | A S |
| `GET/POST /admin/teams`, `PUT/DELETE /admin/teams/{id}/members/{user_id}` | Team management | A S |
| `GET/PUT /admin/policies`, `GET/PUT /admin/projects/{id}/policies` | View/set policies (`production_testing`, approval levels, `llm_limits`) | A (project-scope, cannot enable production) S |
| `GET /admin/audit-events` `?project_id&actor&action&from&to` | Query audit log | A (scope) S |

### Projects and sources
| Method & path | Purpose | Level |
|---|---|---|
| `POST /projects` `{name,description,application_type,team_id?}` | Create (caller becomes owner) | D A S |
| `GET /projects`, `GET /projects/{id}` | List/get accessible projects | read |
| `PATCH /projects/{id}` | Edit name/description/team/team_access | manage |
| `POST /projects/{id}/archive` | Archive | manage |
| `GET/PUT/DELETE /projects/{id}/members/{user_id}` `{access_level}` | Project membership | manage |
| `POST /projects/{id}/sources/zip?name=` — raw `application/zip` body (implemented, Stage 5; multipart deferred, Q38). `POST /projects/{id}/sources` JSON for `git_repository` `{git_url,git_ref?}`, `localhost_url` `{target_url}`, `remote_url` `{target_url,environment}` (implemented: descriptor only, strict validation, nothing contacted, production refused; analysis of these types waits for Stage 6/8, Q36) | Register input source | manage |
| `GET /projects/{id}/sources`, `DELETE /projects/{id}/sources/{sid}` | List / deactivate | read / manage |
| `POST /projects/{id}/sources/{sid}/authorizations` `{environment,paths[],methods[],allowed_risk[],valid_from?,valid_until,justification}` → `201` (**implemented, Stage 6**) | Request authorization for a `remote_url` source (localhost needs none). Hosts are fixed by the source; `environment` must match it; window ≤ 30 days (≤ 24 h production); `allowed_risk` ⊆ low/medium/high; production → `403 policy_blocked` unless the global policy allows it. Creates a `pending` authorization **and** an approval row | manage |
| `GET /projects/{id}/authorizations` | List with `in_effect` (approved and inside its window now) | read |
| `POST /projects/{id}/authorizations/{aid}/revoke` | Revoke an approved authorization (effective for the next gate check) | manage |
| Decision | Authorizations are decided through `POST /approvals/{id}/decision` (single code path; there is no separate `/authorizations/{aid}/decision`). Not by the requester; production needs Super Admin + policy flag + reason ≥ 10 chars | A S |
| `POST /projects/{id}/analyses` `{source_id}` → `201 analysis_snapshot` (synchronous static analysis of a ZIP source until Stage 7 makes it `202`; Q37) | Analyze source (read-only; nothing is executed or extracted) | run |
| `GET /projects/{id}/analyses`, `GET /analyses/{id}` | Snapshots | read |

### Break-glass access (implemented, Stage 6 follow-up)
| Method & path | Purpose | Level |
|---|---|---|
| `POST /projects/{id}/break-glass` `{justification, minutes?}` → `201` | Temporary READ-only access to the project for the calling Super Admin (5-240 min, one active grant, no extension) | S |
| `GET /projects/{id}/break-glass` | Who had emergency access, why, until when | manage |
| `POST /projects/{id}/break-glass/{gid}/revoke` | End it now | grantee or manage |

### Test plans and approvals (implemented, Stage 6)
| Method & path | Purpose | Level |
|---|---|---|
| `POST /projects/{id}/test-plans` `{mode: automatic|prompt_based|developer_defined, snapshot_id?, prompt?, tests?[{check_id, source_id?, name?, parameters?, script_artifact_id?}]}` → `201` | Create a **draft**. Every test comes from the check catalog; there is no field for a command, risk level or approval flag. Each test is `planned`, `skipped` (not applicable), `deferred` (prerequisite missing) or `blocked` (policy / target not authorized), always with a rationale. Rate limited (429) | run |
| `GET /projects/{id}/test-plans`, `GET /test-plans/{id}` | List / get with tests, risk, approval, `content_sha256`, `policy_snapshot`, and `execution_available:false` while no runner exists, and `viewer_can_approve` (UI hint; the decision endpoint re-checks) | read |
| `PATCH /test-plans/{id}` `{summary?, remove_test_ids?[], add_tests?[]}` | Edit while `draft` only; risk and approval need are always recomputed server-side | run |
| `POST /test-plans/{id}/submit` | Freeze a draft: re-check target gates, recompute approval need under the current policy, bind a SHA-256 of the reviewed content. → `approved` automatically if no runnable test needs a human, else `pending_approval` with an approval. `422 no_runnable_tests` if nothing can run | run |
| `POST /approvals/{id}/decision` `{decision: approved|rejected, reason?}` | Decide a plan or authorization approval. Authority comes from `services/policy.py`: explicit project grant, not the requester, org role bound for high/critical, and the project's designated approvers (default: project managers). Reason ≥ 10 chars to approve high/critical. The requester may *reject* (withdraw) their own plan. Refusals are audited as `approval.denied`. Decided approvals are final (`409`) | any eligible project member |
| `GET /approvals?status=pending|approved|rejected|all` | Inbox: for `pending`, only items the caller could approve now | any signed-in user, scoped |
| `GET /projects/{id}/policy` | Effective approval policy incl. `risk_definitions` | read |
| `GET/PUT /admin/policies[/{key}]` `{value}` | Organization keys: `production_testing`, `approval_required_risk_levels`, `allowed_risk_levels`, `high_risk_approver_roles` (subset of developer/admin/super_admin; default admin+super_admin) | S |
| `GET/PUT /projects/{id}/policies[/{key}]` `{value}` | Project keys: `production_testing` (false only), `approval_required_risk_levels`, `allowed_risk_levels`, `risk_approvers` (`{level:[user ids]}`; designees must be active project members, and for high/critical hold an org-allowed role) | manage (any role) |

### Runs, batches, results
| Method & path | Purpose | Level |
|---|---|---|
| `POST /projects/{id}/test-runs` `{plan_id, timeout_seconds?}` + `Idempotency-Key` → `202` | Start a run of an **approved** plan; rejects with `approval_required`/`policy_blocked` (e.g., production, unauthorized target) | run |
| `GET /projects/{id}/test-runs`, `GET /test-runs/{id}` | List/status (progress, counts, timestamps, error) | read |
| `POST /test-runs/{id}/cancel` → `202` | Request cancellation (idempotent) | run |
| `POST /test-runs/{id}/rerun` → `202` | **Not implemented in Stage 7 (Q53)**: new run with `parent_run_id`; destructive tests re-require approval | run |
| `GET /test-runs/{id}/batches`, `GET /test-batches/{id}` | Batch status/attempts | read |
| `GET /test-runs/{id}/results` `?status=` | Per-test results (`passed`, `failed`, `error`, `skipped`, `blocked`, `timed_out`, `cancelled`, `not_run`, `failed_to_start`) | read |
| `GET /test-runs/{id}/results/{result_id}` | One result with its reported cases (name, status, duration, message) and evidence descriptors (id, name, kind, size, sha256) | read |
| `GET /artifacts/{id}/content` | Run evidence only (log/report attached to a run), as an attachment (`nosniff`, `no-store`, CSP), hash re-checked, audited as `artifact.download`; uploads and scripts are not served here | read |
| `GET /test-runs/{id}/events` `?after=` | `job_events` timeline (polling) | read |

### Findings
| Method & path | Purpose | Level |
|---|---|---|
| `GET /projects/{id}/findings` `?severity&status` | List, most severe first (**built, Stage 10**). `verification_state` filter not built | read |
| `GET /projects/{id}/finding-groups` `?limit` | Findings that several scanners/advisories report for the same issue, each member with its own tool, severity and status (**built**, ADR-0008). Groups link; they never merge findings | read |
| `GET /findings/{id}` | Detail: fields (incl. `cwe`, `component`, `aliases`, `group_id`), `confidence`, `limitations`, `events`, linked `evidence`, `attempts`, `related` (other members of its group) (**built**) | read |
| `POST /findings/{id}/status` `{status,note?}` | Review state along an explicit transition map (**built**; replaces the designed `PATCH`). `verified_fixed` and automatic `reopened` come only from scans. `false_positive` / `accepted_risk` need the risk-decision permission (Admin+) and a note of at least 10 characters. Refusals are audited | run (A S for risk decisions) |
| `PATCH /findings/{id}` `{assigned_to?}` | Assignment (**not built**, Q77) | run |
| `POST /findings/{id}/evidence` `{artifact_id,note}` | Attach evidence (**not built**, Q77; scan reports are linked automatically) | run |
| `POST /findings/{id}/verification` `{state,note}` | A person's judgement: `likely`, `confirmed`, `not_reproduced`, `inconclusive`, with a note (**built**). `confirmed` is rejected (`409 evidence_required`, audited) without an evidence row; the database refuses it too. A scan never sets any of these | run |
| `POST /findings/{id}/regression-tests` / `POST /regression-tests/{id}/decision` | Propose/accept regression test (accept = plan edit, subject to approval) | run |
| `POST /findings/{id}/verify-fix` → `202` | Verification run | run |

### Artifacts
| Method & path | Purpose | Level |
|---|---|---|
| `POST /projects/{id}/artifacts` (multipart) | Upload script/ZIP (size/type limits, hashed, `validation_status=pending`) | run |
| `GET /artifacts/{id}` | Metadata | read |
| `GET /artifacts/{id}/content` | Authorized download (attachment, nosniff, audited) | read |

### Operations
`GET /health/live`, `GET /health/ready` (dependency status, no secrets). Reports (`/reports`), alerts (`/alerts`), and chat (`/chat`) are **reserved but not specified** — designed in Stages 12/14.

## Security requirements for the API
No endpoint accepts or returns secrets; passwords/tokens never logged; responses omit `password_hash`, token hashes, internal paths; CORS allow-list from config (frontend origin only, credentials allowed); security headers on all responses; mass assignment prevented by explicit request models; file uploads never executed in the API process; audit event for login success/failure, permission denial, approvals, role changes, artifact download, run start/cancel, policy changes.
