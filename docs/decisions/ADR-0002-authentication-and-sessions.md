# ADR-0002: Authentication and Sessions

- **Status:** Proposed (2026-10-22) — Stage 2 default; needs owner confirmation (OPEN_QUESTIONS Q5)
- **Date:** 2026-10-22

## Context
Blueprint requires Developer/Admin/Super Admin roles with server-enforced authorization. The user asked for an `app_user` schema holding accounts, roles, sessions, and authentication tables. No SSO requirement has been stated for the first release.

## Decision
- Email + password accounts in `app_user.users`; one role per user from `app_user.roles`.
- Passwords hashed with Argon2id; the encoded hash is stored in `password_hash`.
- Server-side sessions in `app_user.sessions`; opaque random token in an HttpOnly cookie; only an HMAC-SHA-256 (keyed with `SESSION_TOKEN_PEPPER`) of the token is stored. Idle and absolute expiry; revocation supported.
- CSRF token per session, sent as `X-CSRF-Token` on state-changing requests.
- No bearer/API tokens and no SSO in the first release.

## Consequences
- Immediate revocation and auditing; no JWT revocation problem. Requires a DB lookup per request (acceptable; indexed).
- Needs `SESSION_TOKEN_PEPPER` secret in the environment; losing it invalidates all sessions (safe failure).
- Adds an Argon2 dependency in Stage 4 (not added in Stage 2).
- Later SSO/OAuth can be added by new tables/columns via migration without changing session handling.

## Alternatives considered
Stateless JWT access tokens (harder revocation), OAuth/SSO only (not requested), database-stored plaintext tokens (rejected).
