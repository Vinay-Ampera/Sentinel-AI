---
description: Design and implement polished, accessible, production-ready
  web interfaces. Use when planning or building Sentinel AI's public
  website, authentication pages, QA dashboards, test reports, findings,
  and responsive application UI.
name: ui-ux-pro
---

# UI/UX Pro Skill

## Purpose

Create clear, polished interfaces that help people understand and act on
information. Prioritize usability, consistency, accessibility, and
maintainability over decoration.

For Sentinel AI, the product is a QA automation and security-testing
platform demonstrated to trainers, company developers, QA engineers, and
HR. The UI should look credible in a professional demo and make test
status, evidence, risks, and next actions easy to understand.

## Required workflow

1.  **Inspect before editing**
    -   Review the existing frontend structure, routing, components, API
        client, authentication flow, styles, tests, and package scripts.
    -   Read the project blueprint, implementation plan, tracker, open
        questions, and repository instructions.
    -   Identify what already works, what is missing, and which backend
        endpoints support each page.
    -   Do not replace working features or invent backend capabilities.
2.  **Plan before implementation**
    -   Propose bounded phases with affected files, dependencies, API
        needs, and verification steps.
    -   Identify any backend gaps separately.
    -   Wait for explicit approval before modifying code when requested
        by the project owner.
3.  **Implement incrementally**
    -   Build shared foundations first, then pages in small, testable
        phases.
    -   Reuse existing components and API integrations.
    -   After each phase, run relevant tests, lint, type checks, and
        build checks available in the repository.
    -   Update the project tracker and documentation truthfully.
4.  **Verify the real experience**
    -   Check loading, success, empty, error, permission-denied,
        conflict, validation, and in-progress states.
    -   Do not report unimplemented or unverified features as working.
    -   Avoid unrelated refactors and unnecessary dependencies.

## Visual direction for Sentinel AI

### Overall style

-   Minimal, modern, professional, calm, and content-focused.
-   Use the provided test execution report screenshot as a layout
    reference for reports: clear heading and metadata, compact summary
    metrics, restrained progress indicator, filters, and readable result
    rows.
-   Use the supplied website references for inspiration, not as designs
    to copy.
-   Avoid a generic template appearance, excessive gradients,
    glassmorphism, oversized shadows, decorative clutter, and large
    saturated color blocks.

### Color system

Use a restrained neutral palette: - Neutral page and surface
backgrounds. - High-contrast primary text and muted secondary text. -
Subtle borders and separators. - One restrained accent for primary
actions and selected states. - Muted semantic colors for success,
failure, warning, and information only when needed.

Never communicate status through color alone. Include text labels and,
where useful, icons. Keep semantic colors distinguishable in all themes
and verify contrast.

### Themes

Support **Light**, **Dark**, and **System** modes. - Define theme tokens
as CSS custom properties rather than duplicating component styles. -
System mode follows `prefers-color-scheme`. - Persist the user's
explicit selection across refreshes. - Avoid a flash of the wrong theme
on initial load where practical. - Check charts, tables, dialogs, menus,
focus indicators, code/evidence views, and status badges in all
themes. - Do not hard-code colors inside individual components when a
design token exists.

### Layout and navigation

-   Use a **top navbar only; do not add a sidebar**.
-   Make navigation responsive, keyboard-operable, and clear on narrow
    screens.
-   Keep page titles, context, primary actions, and breadcrumbs (when
    useful) consistent.
-   Keep the public marketing site visually distinct from the
    authenticated application while sharing the same design tokens.
-   Do not cram every route into the navbar; use appropriate page-level
    navigation patterns without introducing a sidebar.

### Typography and spacing

-   Use a legible sans-serif typeface with a clear hierarchy.
-   Prefer consistent spacing, line lengths, alignment, and restrained
    corner radii.
-   Use whitespace to separate content rather than unnecessary boxes.
-   Keep body text readable and secondary information visibly
    subordinate without making it too faint.
-   Avoid overly small labels and dense tables that become unusable on
    mobile.

## Sentinel AI page guidance

### Public homepage

Explain the product quickly: QA automation, test execution and
reporting, security findings, evidence, and accessibility testing
capabilities where implemented. - Clear headline and concise supporting
copy. - Primary action for getting started and secondary action to
explore the product. - A QA-inspired visual or genuine product preview,
not generic AI imagery. - A concise workflow explanation and capability
overview. - Be precise about which capabilities are available now versus
planned. - Include a clear sign-in route. - Do not claim accessibility
conformance or automatic coverage beyond what the product verifies.

### Sign-in and account pages

-   Match the product's visual system.
-   Use explicit labels, appropriate autocomplete attributes, password
    show/hide controls, and understandable validation.
-   Provide clear loading and error feedback without exposing secrets or
    internal details.
-   Implement sign-up only if the backend and account policy support it.
    Otherwise, use the supported invitation or access-request flow.
-   Never invent authentication endpoints or weaken server-side
    authorization.

### QA dashboard and reports

-   Present the most useful facts first: run status, counts, duration,
    environment, and last-updated time when available.
-   Use neutral metric cards and restrained semantic accents.
-   Keep result states distinct: pass, fail, skip, blocked, timed out,
    failed to start, and not run must not be conflated.
-   Add usable filters, sorting, pagination, and empty states where the
    data size warrants them.
-   Show evidence and limitations in context.
-   Distinguish tool-reported findings from independently verified
    findings.
-   Never imply that a scan ran or a test passed if it did not.

### Security findings and governance

-   Make severity, confidence, source tool, verification state,
    evidence, and remediation guidance easy to distinguish.
-   Show duplicate relationships without discarding each finding's
    source evidence or status.
-   Explain why risky actions are unavailable and show required
    authorization/approval states.
-   Confirm destructive actions and require reasons for risky actions
    where the backend requires them.
-   Treat role-aware UI as a usability aid; the backend remains the
    authority for access control.

### Future-stage features

-   Use clearly marked "Planned" or "Coming in Stage N" placeholders
    only when helpful.
-   Do not make placeholder controls look functional.
-   Do not start a paused stage or implement its features as part of
    frontend work without explicit approval.

## Accessibility requirements

Target WCAG 2.2 AA practices where applicable; do not claim formal
conformance without appropriate evaluation. - Semantic HTML and a
logical heading hierarchy. - Full keyboard operation and visible focus
states. - Correct labels, accessible names, descriptions, and error
associations. - Sufficient text and non-text contrast. - Focus
management for dialogs, menus, and route changes where appropriate. -
Respect reduced-motion preferences. - Do not rely on color alone. -
Ensure responsive zoom/reflow and usable touch targets. - Provide
accessible names for icon-only controls. - Run automated checks such as
axe-core when available, but explain that automated scans cannot prove
complete accessibility. Include manual keyboard and screen-reader checks
in the verification plan.

## Interaction states and feedback

Every data-driven page should account for: - Initial loading and
background refresh. - Empty state with a helpful next action. - Error
state with safe, actionable feedback and retry where appropriate. -
Success feedback for completed actions. - Validation errors close to the
relevant field. - Permission denied and conflict responses. -
Long-running operations, progress, cancellation, and stale data where
applicable. - Disabled actions with an understandable reason.

Use consistent patterns for buttons, links, forms, tables, filters,
dialogs, toasts, badges, and confirmation prompts.

## Responsive behavior

-   Design from narrow screens through desktop.
-   At small widths, collapse navbar items into an accessible menu.
-   Convert wide tables into responsive layouts or provide intentional
    horizontal scrolling with clear cues.
-   Prevent clipped dialogs, overflowing code/evidence, and hidden
    primary actions.
-   Verify realistic viewport sizes, not just a single desktop
    screenshot.

## Engineering rules

-   Follow the project's existing framework, file organization,
    conventions, and CSS strategy unless there is a clear reason to
    change them.
-   Keep component styles close to components if that is the existing
    convention.
-   Use reusable components for shared controls and design tokens for
    consistency.
-   Avoid unnecessary libraries and large dependencies.
-   Do not use fake data in production flows. If demo fixtures are used,
    label them clearly and keep them separate from real API data.
-   Handle API errors deliberately, including relevant 401, 403, 409,
    and 422 responses.
-   Do not expose secrets, tokens, sensitive evidence, or internal stack
    traces in the UI.
-   Keep existing functionality unless an approved requirement
    explicitly changes it.

## Definition of done

Before calling a page or phase complete: - Requirements and existing API
contracts have been checked. - Light, Dark, and System themes have been
reviewed. - Keyboard navigation, focus, labels, contrast, and responsive
layout have been checked. - Loading, empty, error, success, and
permission states are handled. - Relevant tests, lint, and build checks
pass, or remaining failures are documented precisely. - No fake
functionality or unsupported claims remain. - Documentation and tracker
reflect the actual implementation and verification level. - Changes are
limited to the approved scope.

## Expected response format when using this skill

Before coding, summarize: 1. Existing functionality to reuse. 2. Pages
and components to add or change. 3. API/backend gaps. 4. Implementation
phases and verification plan. 5. Risks or decisions requiring owner
approval.

After each approved phase, summarize files changed, behavior
implemented, checks run and results, known limitations, and the next
proposed phase. Do not start the next phase without approval when the
owner requests step-by-step control.
