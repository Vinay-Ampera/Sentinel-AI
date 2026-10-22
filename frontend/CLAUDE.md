# Frontend Instructions (React / Vite / JavaScript)

Read the root `CLAUDE.md` first. Status: Stage 1 scaffold (static heading only; no features).

## Stack (initial decisions, see ADR-0001)
React + Vite + JavaScript, React Router, CSS variables with a consistent component system (UI library only if it clearly helps and is accessible).

## Layout
`src/app/`, `routes/`, `components/` (shared), `features/` (by product area: projects, test runs, findings, observability, administration), `hooks/`, `services/` (API client), `types/`, `utils/`. Create folders when needed.

## Rules
- All backend communication goes through the shared client in `services/`; no ad-hoc `fetch` in components. API base is `/api/v1`.
- Plain JavaScript (JSX), no TypeScript (owner decision). Validate API response shapes at the service-layer boundary; consider JSDoc for documenting shapes.
- Every data view handles loading, error, empty, and progress states. Use polling for job progress initially.
- Accessibility: semantic markup, keyboard support, visible focus, labels, sufficient contrast. Plan axe-core checks.
- Role-based UI is usability only; the backend is authoritative for authorization.
- Never put secrets or provider keys in browser code or `VITE_*` variables. Only `.env.example` is committed.
- Display evidence, uncertainty, and limitations honestly; never render a result as passed/confirmed without backend evidence.

## Commands (run from `frontend/`; verified in Stage 1)
`npm install`, `npm run dev`, `npm run build`, `npm run lint` (oxlint, Vite template default), `npm test` (Vitest + jsdom + Testing Library; tests in `tests/`). Node 24.
