// What the product does today, worded to match PROJECT_TRACKER.md. "available" means built and
// verified; "partial" means built with a stated limit; "planned" names the stage that will
// build it. Keep this in step with the tracker: nothing here may claim more than it records.
export const CAPABILITIES = [
  {
    id: 'intake',
    title: 'Project intake and analysis',
    level: 'available',
    text: 'Upload a ZIP and get a static analysis of languages, frameworks, test tooling and coverage gaps. No project code is run during analysis. Git, localhost and remote sources can be registered but are not analysed yet.',
  },
  {
    id: 'planning',
    title: 'Test plans and approvals',
    level: 'available',
    text: 'A recommended plan lists each check with its rationale, risk and prerequisites. Higher-risk checks need an eligible approver, and the reason is recorded.',
  },
  {
    id: 'execution',
    title: 'Sandboxed test runs',
    level: 'partial',
    text: 'Python (pytest) checks run in an isolated, locked-down container with progress, cancellation and per-test results. Running project code is switched on per deployment by the operator. Browser (Playwright) tests are not built yet.',
  },
  {
    id: 'evidence',
    title: 'Results and evidence',
    level: 'available',
    text: 'Passed, failed, skipped, blocked, timed out and could-not-start stay distinct, and the logs and reports behind each result can be opened.',
  },
  {
    id: 'security',
    title: 'Security findings',
    level: 'partial',
    text: 'Bandit and an offline dependency audit are verified. Semgrep and OWASP ZAP are integrated but not yet verified against the real tools, and ZAP is off by default. Findings stay unverified until a person confirms them.',
  },
  {
    id: 'governance',
    title: 'Governance and access',
    level: 'available',
    text: 'Roles, project membership, target authorizations, approval policies and time-limited break-glass access, all enforced by the server and recorded.',
  },
  { id: 'ai', title: 'AI-assisted investigation and regression tests', level: 'partial', text: 'Suggested test plans, failure investigation and drafted regression tests from stored evidence, filtered and validated, always for a person to review. Not yet verified across real-model use.' },
  { id: 'observability', title: 'Observability and alerts', level: 'partial', text: 'Applications push structured error events (or OpenTelemetry logs); Sentinel groups and redacts them and raises measured alerts. Some parts are available and some are not: see "Observability and alerts: what works today" below for each feature, its setup and its limits.' },
  { id: 'a11y', title: 'Accessibility and LLM security testing', level: 'planned', when: 'validation phase', text: 'Accessibility checks of the applications under test, and tests for prompt-injection and agent risks.' },
  { id: 'reports', title: 'Reports and evidence-grounded chat', level: 'planned', stage: 13, text: 'Reports and questions answered only from recorded evidence.' },
  { id: 'regression', title: 'Regression and fix verification', level: 'planned', stage: 14, text: 'Re-run checks to confirm a fix and compare runs.' },
]

export const WORKFLOW = [
  { title: 'Analyze', text: 'Inspect the project without running it.' },
  { title: 'Plan', text: 'Propose relevant checks with their risk and rationale.' },
  { title: 'Approve', text: 'An eligible person approves what may run.' },
  { title: 'Run', text: 'Execute approved checks in an isolated sandbox.' },
  { title: 'Review evidence', text: 'Open the logs and reports behind every result and finding.' },
]
