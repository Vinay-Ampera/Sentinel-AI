# ADR-0002: Authentication and Sessions

- **Status:** Accepted and implemented in Stage 4 (2026-10-22). The owner instructed Stage 4 to follow this design; no objection recorded to the Stage 2 proposal.
- **Date:** 2026-10-22

## Context
Blueprint requires Developer/Admin/Super Admin roles with server-enforced authorization. The user asked for an `app_user` schema holding accounts, roles, sessions, and authentication tables. No SSO requirement has been stated for the first release.

## Decision
- Email + password accounts in `app_user.users`; one role per user from `app_user.roles`.
- Passwords hashed with Argon2id; the encoded hash is stored in `password_hash`.
- Server-side sessions in `app_user.sessions`; opaque random token in an HttpOnly cookie; only an HMAC-SHA-256 (keyed with `SESSION_TOKEN_PEPPER`) of the token is stored. Idle and absolute expiry; revocation supported.
- CSRF token per session, sent as `X-CSRF-Token` on state-changing requests.
- No bearer/API tokens and no SSO in the first release, **except the project ingest key** (amendment 2026-10-24 below).

## Consequences
- Immediate revocation and auditing; no JWT revocation problem. Requires a DB lookup per request (acceptable; indexed).
- Needs `SESSION_TOKEN_PEPPER` secret in the environment; losing it invalidates all sessions (safe failure).
- Adds an Argon2 dependency in Stage 4 (not added in Stage 2).
- Later SSO/OAuth can be added by new tables/columns via migration without changing session handling.

## Alternatives considered
Stateless JWT access tokens (harder revocation), OAuth/SSO only (not requested), database-stored plaintext tokens (rejected).

## Implementation notes (Stage 4)
- The CSRF token is `HMAC(pepper, "csrf-token:" + session_token)`; only its keyed hash is stored (`csrf_token_hash`), so `GET /auth/me` can re-issue it and it is useless without the session cookie.
- Cookie and CSRF checks use constant-time comparison; `Origin`, when present on state-changing requests, must be in `CORS_ALLOWED_ORIGINS`.
- Login failures (unknown, inactive, locked, wrong password) return one identical 401; the reason is audit-only. A dummy Argon2 verify equalises timing for unknown accounts.
- The client IP is the direct peer address; `X-Forwarded-For` is not trusted unless the operator lists the proxy in `TRUSTED_PROXY_CIDRS` (added in Stage 12; empty by default; then the header is honoured only for requests that arrive from a listed proxy, and the right-most untrusted hop is the client).
- The per-IP rate limiter is in-process (per worker); the database lockout is the authoritative brute-force control.

## Amendment (2026-10-24, Stage 12): project ingest keys are the one exception to "no bearer tokens"
Approved by the owner (Q123). A push model for application events has no browser and no session, so it needs one machine credential. The exception is deliberately narrow and does not weaken the session design:
- **What it is:** a project-scoped *ingest key* `sai_ing_<12-hex key id>_<32 random bytes, urlsafe>`, sent as `Authorization: Bearer <key>` to `POST /api/v1/ingest/events` only. It is not a user, has no role, and every other route rejects it (they accept only the session cookie).
- **Storage:** like a session token, only a keyed hash is stored (HMAC-SHA-256 with `SESSION_TOKEN_PEPPER`, purpose `ingest-key`); the secret is shown once at creation; comparison is constant time; unknown, malformed, expired, revoked and archived-project keys return one identical `401`.
- **Scope and lifetime:** one project, one capability (add events); created, listed and revoked only by project managers; default 90 days (maximum 365), at most 5 active per project, revocation effective on the next request; creation and revocation are audited and the key never appears in an audit row, log or list.
- **CSRF and cookies:** the route ignores cookies and applies no CSRF check (there is no ambient credential to forge); CORS does not allow the `Authorization` header from browsers, so it is a server-to-server path.
- **Abuse limits:** per-key request and event rate limits, a per-project daily quota, per-address throttling of failed keys (in process; Q136), and payload and schema bounds. A stolen key can only add (redacted, capped) events to its own project; it cannot read, change a finding, run or approval, or start a model call.
- Everything else in this ADR is unchanged: no API tokens for people, no SSO, no other bearer credential. Details and tests: ADR-0011 and `tests/integration/test_observability.py`.
