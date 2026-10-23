// What is designed but not built, worded to match docs/IMPLEMENTATION_PLAN.md. Nothing here is
// available; the page that shows it has no controls. Keep it in step with the plan.
export const ROADMAP = [
  {
    stage: 11,
    title: 'AI-assisted workflows',
    note: 'Paused until the project owner approves it.',
    text: 'Investigation of failures, proposed regression tests and fix verification, using model output that is filtered, validated and recorded.',
    items: ['Evidence is filtered and redacted before any model sees it', 'Model output can never override permissions, approvals or sandbox rules', 'Time, retry and cost limits, with usage recorded'],
  },
  {
    stage: 12,
    title: 'Observability and alerts',
    text: 'Bring in logs and traces, correlate them with runs and findings, and turn real failures into proposed tests.',
    items: ['Noise filtering and thresholds you can configure', 'Alerts you can acknowledge', 'Links between an alert, a run and a finding'],
  },
  {
    stage: 13,
    title: 'Accessibility and LLM security testing',
    text: 'Accessibility checks of the applications you analyze, and tests for prompt injection and agent risks.',
    items: ['Automated accessibility results with their limits stated', 'Prompt-injection and agent-misuse probes', 'Telemetry for agent behaviour'],
  },
  {
    stage: 14,
    title: 'Reports and evidence-grounded chat',
    text: 'Reports, history, and a chat that answers only from recorded evidence.',
    items: ['Answers cite the evidence they rest on', 'Exportable reports', 'A searchable history of runs and decisions'],
  },
  {
    stage: 15,
    title: 'Regression verification',
    text: 'Re-run checks to confirm a fix, compare runs, and harden reliability.',
    items: ['Run-to-run comparison', 'Fix verification against the original failure', 'Reliability measures for the platform itself'],
  },
  {
    stage: 16,
    title: 'Deployment readiness',
    text: 'Continuous integration, containers, production configuration review and documentation.',
    items: ['Automated checks on every change', 'Deployment guidance matched to what was tested'],
  },
]

// Things that exist but have a stated limit today.
export const LIMITS = [
  'Browser (Playwright) tests are not built yet.',
  'Semgrep and OWASP ZAP are integrated but have not been verified against the real tools; ZAP is off by default.',
  'Git, localhost and remote sources can be registered but are not analysed or fetched yet.',
  'Running project code in the sandbox is switched on per deployment by the operator.',
]
