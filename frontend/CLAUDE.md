# Frontend Instructions (React / Vite / JavaScript)

Read the root `CLAUDE.md` first. Current implementation status is in `docs/PROJECT_TRACKER.md`.

## Stack (initial decisions, see ADR-0001)
React + Vite + JavaScript, React Router, CSS variables with a consistent component system (UI library only if it clearly helps and is accessible).

## Architecture and file organization (mandatory for F0-F9 and all later frontend work)
The UI is **component-based and page-based**. Reuse before writing: search `src/components/`, `src/hooks/` and `src/lib/` first, and extract shared code instead of copying it.

| Folder | Holds | Rules |
|---|---|---|
| `src/pages/` | Route-level pages (`SomethingPage.jsx` + `SomethingPage.css` if needed) | A page composes components and feature pieces, calls hooks/services, and owns its `PageHeader`. One page per route. |
| `src/components/` | Shared, reusable UI (Button, Card, DataTable, Dialog, ...) | No feature or API knowledge; tokens only; props in, events out. |
| `src/features/<area>/` | Components specific to one product area (plans, runs, findings, ...) | Used by pages; may import `components/`, never another feature's internals. Area-only labels live here. |
| `src/app/` | Application shell: `App`, router, `AppShell`, `Navbar`, providers | Not pages. |
| `src/hooks/` | Every custom hook, including the hook that reads a context | `useX.js`; providers stay with the shell/theme code. |
| `src/services/` | The API client only (`api.js`) | All backend calls; no `fetch` anywhere else. |
| `src/lib/` | Pure helpers (status vocabulary, error mapping) | No React. |
| `src/theme/` | Theme logic and provider | |
| `src/styles/` | **Global only:** `tokens.css` (theme variables), `base.css` (reset, bare elements, genuinely global utilities) | Never component styles. |

**CSS rule:** every component or page that needs styles has a CSS file **next to its JSX file with the same base name** (`Button.jsx` + `Button.css`, `Navbar.jsx` + `Navbar.css`) and imports it from that JSX file. No shared "ui.css" or "shell.css" files, and no component styles in `src/styles/`. Colours, spacing, radii and fonts come from tokens; a component's CSS uses its own class names (not another component's). Global CSS is limited to theme variables, resets, bare-element defaults and utilities used in more than one place (`.visually-hidden`, `.muted`, `.error`, `.stack`).

**Naming:** components, pages and their CSS are `PascalCase`; hooks are `useThing.js`; helpers and services are `camelCase.js`; one component per file unless the extras are tiny parts of the same component (for example `Metric` beside `Card`).

**Known deviations to resolve in their own phases (not refactored early):** `features/plans/plans.css` and `features/runs/runs.css` are shared by several panels rather than paired with one JSX file; `PlanReview` keeps its older markup and loader (and `plans.css`, shared with the plan screens). The findings (F6) and runs (F5) features were rebuilt and no longer have panels.

**Testing (keep it efficient):** add tests for critical logic, API interactions, authentication/route protection, approval and other decision workflows, and security-relevant helpers. Do not write a test per simple presentational component. Shared pages and components are covered through those workflows plus the axe checks in `tests/a11y.test.jsx`.

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
