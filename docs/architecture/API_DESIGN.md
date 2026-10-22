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
| `POST /projects/{id}/sources` — JSON for `git_repository` `{git_url,git_ref?}`, `localhost_url` `{target_url}`, `remote_url` `{target_url,environment}`; multipart for `zip_upload` | Register input source | manage |
| `GET /projects/{id}/sources`, `DELETE /projects/{id}/sources/{sid}` | List / deactivate | read / manage |
| `POST /projects/{id}/sources/{sid}/authorizations` `{environment,scope{hosts,paths,methods},allowed_risk,valid_from,valid_until,justification}` → `202` | Request authorization for a remote target | manage |
| `POST /authorizations/{aid}/decision` `{decision,note}` | Approve/reject (not by requester; production needs S + policy enabled) | A S |
| `POST /projects/{id}/analyses` `{source_id}` → `202 analysis_snapshot` | Analyze source (read-only, in sandbox for code) | run |
| `GET /projects/{id}/analyses`, `GET /analyses/{id}` | Snapshots | read |

### Test plans and approvals
| Method & path | Purpose | Level |
|---|---|---|
| `POST /projects/{id}/test-plans` `{snapshot_id?, mode: automatic|prompt_based|developer_defined, prompt?, tests?[]}` → `201`/`202` | Create plan (recommendations / prompt-driven / developer-defined). Developer-defined `tests[]` reference tool adapters + definition or an uploaded `script` artifact; never raw shell | run |
| `GET /projects/{id}/test-plans`, `GET /test-plans/{id}` | List/get with planned tests, risk, approval status, rationale | read |
| `PATCH /test-plans/{id}` | Edit while `draft` (add/remove/reorder tests) | run |
| `POST /test-plans/{id}/submit` | `draft → pending_approval` (or `approved` automatically if every test is low risk and policy allows) | run |
| `POST /approvals/{id}/decision` `{decision: approved|rejected, reason}` | Decide an approval; requester cannot self-approve high/critical | A S (D only if policy delegates `low`/`medium`) |
| `GET /approvals?status=pending` | Approval inbox (scoped) | A S |

### Runs, batches, results
| Method & path | Purpose | Level |
|---|---|---|
| `POST /projects/{id}/test-runs` `{plan_id, timeout_seconds?}` + `Idempotency-Key` → `202` | Start a run of an **approved** plan; rejects with `approval_required`/`policy_blocked` (e.g., production, unauthorized target) | run |
| `GET /projects/{id}/test-runs`, `GET /test-runs/{id}` | List/status (progress, counts, timestamps, error) | read |
| `POST /test-runs/{id}/cancel` → `202` | Request cancellation (idempotent) | run |
| `POST /test-runs/{id}/rerun` → `202` | New run with `parent_run_id`; destructive tests re-require approval | run |
| `GET /test-runs/{id}/batches`, `GET /test-batches/{id}` | Batch status/attempts | read |
| `GET /test-runs/{id}/results` `?status=` | Per-test results | read |
| `GET /test-runs/{id}/events` `?after=` | `job_events` timeline (polling) | read |

### Findings
| Method & path | Purpose | Level |
|---|---|---|
| `GET /projects/{id}/findings` `?severity&status&verification_state` | List | read |
| `GET /findings/{id}` | Detail incl. evidence list and events | read |
| `PATCH /findings/{id}` `{status?,assigned_to?}` | Triage; `accepted_risk`/`false_positive` need Admin+ | run (A S for risk acceptance) |
| `POST /findings/{id}/evidence` `{artifact_id,note}` | Attach evidence | run |
| `POST /findings/{id}/verification` `{state}` | Set verification state; `confirmed` rejected (`409`) without evidence | run |
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
