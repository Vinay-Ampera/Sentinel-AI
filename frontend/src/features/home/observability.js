// Stage 12 (observability and alerts), feature by feature, worded to match PROJECT_TRACKER.md and
// ADR-0011. The three levels mean:
//   available    built, tested, and exercised end to end on a live system, with no functional gap
//                that this entry does not state;
//   partial      built and tested, but part of it is unverified, opt-in or limited as stated;
//   unavailable  not built (nothing here can be used).
// `needs` is the configuration or access it takes; `limits` is what it does not do or has not
// proved. Nothing here may claim more than the tracker records.
export const LEVELS = {
  available: 'Built, tested and checked end to end on a live system.',
  partial: 'Built and tested, with a part unverified, opt-in or limited as stated.',
  unavailable: 'Not built. Nothing here can be used.',
}

export const OBSERVABILITY = [
  {
    id: 'alert-lifecycle',
    title: 'Alert list, acknowledge and resolve',
    level: 'available',
    text: 'Each project has an Alerts tab with severity, source, evidence, history and notes. Acknowledge means seen, resolve closes it, and every change is recorded in the audit log.',
    needs: 'Project access: read to view, run to acknowledge or resolve.',
    limits: 'An alert states what was measured, never why it happened. No cause is claimed until an investigation exists, and even then it is a hypothesis.',
  },
  {
    id: 'internal-alerts',
    title: 'Alerts from Sentinel\'s own runs and findings',
    level: 'available',
    text: 'A failed or timed-out test run and a finding that a later scan reports again raise an alert from records Sentinel already holds, with links to the run, result or finding.',
    needs: 'Nothing to configure.',
    limits: 'A run you cancel yourself raises no alert.',
  },
  {
    id: 'org-limits',
    title: 'Organization limits for alert thresholds',
    level: 'available',
    text: 'A super admin can narrow the range of every alert threshold on the Administration page. Projects stay inside it, and an existing value outside a new limit is treated as the nearest limit.',
    needs: 'Super admin role.',
    limits: 'Limits can only narrow the built-in ranges, never widen them.',
  },
  {
    id: 'ingestion',
    title: 'Error events pushed by your application',
    level: 'partial',
    text: 'An application sends structured error events with a project ingest key. Sentinel redacts secrets before storing, drops repeats of the same event id for 24 hours, and keeps grouped counts and a few samples, not a raw log stream.',
    needs: 'A project manager turns ingestion on (it is off for every project) and creates an ingest key on the Alerts tab. The application sends events to POST /api/v1/ingest/events with that key.',
    limits: 'Only warning, error and fatal events are kept. Redaction is pattern based and can miss unknown secret shapes. Checked with a purpose-built test program, not with real application logs or over several days.',
  },
  {
    id: 'rules',
    title: 'Error groups and alert rules with tunable thresholds',
    level: 'partial',
    text: 'Similar errors are grouped. Fixed rules raise an alert for a new error, a rate spike, silence after activity and dropped events, and project managers can tune the thresholds within limits.',
    needs: 'Ingestion turned on. Thresholds are set per project by a manager within the organization limits.',
    limits: 'The default thresholds and the grouping have not been tried on real telemetry. A quiet alert list with no events received is not evidence that the application is healthy; the page says so.',
  },
  {
    id: 'otel',
    title: 'OpenTelemetry logs and trace correlation',
    level: 'partial',
    text: 'OpenTelemetry log records (OTLP over HTTP, JSON) are accepted through the same pipeline. Events that carry the trace id of one of Sentinel\'s runs are linked to it, and a trace page shows both.',
    needs: 'An ingest key, and an OpenTelemetry exporter set to the JSON encoding and pointed at /api/v1/ingest/otlp with the key.',
    limits: 'JSON only: no protobuf, compression, spans or metrics. Tested with hand-built records and a live server, not with a real OpenTelemetry exporter. Sharing a trace id is shown as correlation, never as cause.',
  },
  {
    id: 'cost',
    title: 'Model cost and run-duration alerts',
    level: 'partial',
    text: 'Alerts for unusually high estimated model cost, assistant workflows running too often, many failed model calls, and runs far slower than earlier runs of the same plan. Model use is summarised with every cost labelled as an estimate.',
    needs: 'Model use configured (otherwise there is nothing to measure). Set the real model prices (LLM_PRICE_*) for meaningful cost figures.',
    limits: 'Costs are estimates from token counts and configured prices. The default limits are untested on real usage. CPU and memory of your applications are not measured.',
  },
  {
    id: 'loop',
    title: 'Investigate an alert and draft a regression test',
    level: 'partial',
    text: 'From an alert a person can ask the assistant to investigate, or to draft a regression test when there is an error type and a stack trace, at least two occurrences and an analysed source with a supported test framework. If something is missing, the result says what.',
    needs: 'Run access, and the assistant model configured on the server.',
    limits: 'Suggestions only: a drafted test is stored text that is never added to your project, committed or run. Only light real-model use has been checked. Nothing starts a model call just because an alert fired.',
  },
  {
    id: 'scheduled',
    title: 'Scheduled alert evaluation and clean-up',
    level: 'partial',
    text: 'A background schedule re-checks the rules that depend on time (silence, model cost) without anyone opening the page, and can delete expired events.',
    needs: 'An operator runs the Celery beat process. Evaluation is on by default; automatic deletion stays off until EVENT_PURGE_ENABLED=true. Retention defaults to 30 days for samples and 180 days for groups.',
    limits: 'Nothing in the repository starts the beat process for you yet. It has run only in a lab with a real worker and beat, never as a deployed service.',
  },
  {
    id: 'shared-limits',
    title: 'Rate limits shared across API processes',
    level: 'partial',
    text: 'Login, plan, assistant and ingestion limits can be counted in Redis so every API process shares one budget. If Redis is unreachable each process falls back to its own count.',
    needs: 'RATE_LIMIT_BACKEND=redis and a reachable Redis. Behind a reverse proxy, TRUSTED_PROXY_CIDRS lists the proxies. The default keeps limits inside each process.',
    limits: 'A fixed window, so up to twice the limit can pass across a window edge. Checked with a throwaway Redis, not in a deployment.',
  },
  {
    id: 'notifications',
    title: 'Email, chat or webhook notifications',
    level: 'unavailable',
    text: 'Alerts are shown in the Alerts tab only. Nothing is sent to anyone.',
    needs: null,
    limits: 'Not built. Someone has to open the project to see an alert.',
  },
  {
    id: 'logs-metrics',
    title: 'Metrics, trace spans and a searchable log store',
    level: 'unavailable',
    text: 'Sentinel keeps grouped counts and a few redacted samples. It does not store spans or metrics, and it has no log search.',
    needs: null,
    limits: 'Not built. Keep using your existing logging and tracing tools alongside it.',
  },
  {
    id: 'third-party',
    title: 'Pulling from tools such as Datadog, Sentry or Loki',
    level: 'unavailable',
    text: 'Events reach Sentinel only when your application, or an OpenTelemetry exporter, pushes them.',
    needs: null,
    limits: 'Not built. No outbound connection to third-party monitoring services exists.',
  },
  {
    id: 'verify-from-alert',
    title: 'Confirming a fix from an alert',
    level: 'unavailable',
    text: 'An alert can lead to a drafted test, but Sentinel does not yet run it to show the failure reproduced or the fix worked.',
    needs: null,
    limits: 'Not built. It belongs with fix verification in a later stage.',
  },
]

export const LEVEL_ORDER = ['available', 'partial', 'unavailable']
