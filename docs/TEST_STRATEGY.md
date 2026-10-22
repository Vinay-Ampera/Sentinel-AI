# Test Strategy

> Status: SKELETON from plan §13. No tests exist yet. Anything not run must be reported as "not run".

- **Backend:** unit (services, permissions, policy, state transitions, parsers); API integration on a test DB; job tests (retry, cancel, idempotency, recovery); sandbox tests (no secrets mounted, limits applied); cross-project access tests.
- **Frontend:** component/utility; route/role; loading/error/empty/progress states; Playwright E2E; axe-core on key flows.
- **Integration:** intake → plan → policy → run → sandbox → result → UI; cancel queued/running; worker restart; finding → regression test → verify; user A cannot read user B's data.

## TODO
Tooling choices (Vitest? ruff/mypy?), fixtures, coverage targets, CI wiring.
