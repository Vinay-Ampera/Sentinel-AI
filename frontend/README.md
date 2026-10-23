# Sentinel AI — Frontend

React + Vite + JavaScript. See `CLAUDE.md`, `../docs/IMPLEMENTATION_PLAN.md` (stages) and `../docs/PROJECT_TRACKER.md` (current status).

## Prerequisites
Node.js 24, npm.

## Commands
```bash
npm install
npm run dev      # http://localhost:5173
npm run build    # production build (vite build)
npm run lint     # oxlint (Vite template default)
npm test         # Vitest (jsdom), incl. axe and contrast checks
```

## Environment variables
None required yet. `.env.example` lists a placeholder; only public, non-secret values may use the `VITE_` prefix.

## Themes and component gallery
Light, Dark and System themes are stored in `localStorage` (`sentinel-theme`). In development, `/design-system` shows every shared component (compiled out of production builds).

## Structure
See `CLAUDE.md` ("Architecture and file organization"): pages in `src/pages/`, shared components in `src/components/`, feature pieces in `src/features/`, hooks in `src/hooks/`, API client in `src/services/`; each component's CSS sits beside its JSX; only theme variables and resets are global (`src/styles/`).

