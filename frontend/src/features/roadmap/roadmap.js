// What is designed but not built, worded to match docs/IMPLEMENTATION_PLAN.md. Nothing here is
// available; the page that shows it has no controls. Keep it in step with the plan.
export const ROADMAP = [
  {
    when: 'validation phase',
    title: 'Accessibility and LLM security testing',
    text: 'Accessibility checks of the applications you analyze, and tests for prompt injection and agent risks.',
    items: ['Automated accessibility results with their limits stated', 'Prompt-injection and agent-misuse probes', 'Checks that run only where they apply and are authorized'],
  },
  {
    stage: 13,
    title: 'Reports and evidence-grounded chat',
    text: 'Reports, history, and a chat that answers only from recorded evidence.',
    items: ['Answers cite the evidence they rest on', 'Exportable reports', 'A searchable history of runs and decisions'],
  },
  {
    stage: 14,
    title: 'Regression verification',
    text: 'Re-run checks to confirm a fix, compare runs, and harden reliability.',
    items: ['Run-to-run comparison', 'Fix verification against the original failure', 'Reliability measures for the platform itself'],
  },
  {
    stage: '15-16',
    title: 'Deployment readiness',
    text: 'Continuous integration, containers, production configuration review and documentation.',
    items: ['Automated checks on every change', 'Deployment guidance matched to what was tested'],
  },
]

// Things that exist but have a stated limit today.
export const LIMITS = [
  'The assistant (test planning, failure investigation, regression drafts) has been checked with test doubles and one real model request; wider real-model use, answer quality and cost figures are not yet verified.',
  'Observability and alerts: checked with a purpose-built test program, hand-built OpenTelemetry records and a real Redis and Celery in a lab, never with real application logs or a real OpenTelemetry exporter. Email, chat and webhook notifications, metrics, spans and log search are not built.',
  'Browser (Playwright) tests are not built yet.',
  'Semgrep and OWASP ZAP are integrated but have not been verified against the real tools; ZAP is off by default.',
  'Git, localhost and remote sources can be registered but are not analysed or fetched yet.',
  'Running project code in the sandbox is switched on per deployment by the operator.',
]
