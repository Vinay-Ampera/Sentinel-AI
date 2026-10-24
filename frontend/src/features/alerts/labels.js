// Wording for alerts. An alert states what Sentinel measured; it never states a cause.
export const RULE = {
  new_error_group: 'New error',
  error_rate_spike: 'Error rate spike',
  run_failed: 'Test run failed',
  finding_reopened: 'Finding reopened',
  telemetry_gap: 'No events received',
  ingest_dropping: 'Events being dropped',
  alert_overflow: 'More alerts than the limit',
}

export const ruleLabel = (v) => RULE[v] || String(v).replace(/_/g, ' ')

export const SOURCE = {
  external: 'Reported by the application',
  internal: 'Observed by Sentinel',
}

export const sourceLabel = (v) => SOURCE[v] || 'Unknown source'

export const CAUSE = {
  not_investigated: 'Not investigated. Sentinel does not know why this happened.',
  investigated: 'Investigated: the assistant suggested hypotheses from stored evidence. None is confirmed.',
}

export const causeLabel = (v) => CAUSE[v] || CAUSE.not_investigated

export const HISTORY = {
  created: 'Raised',
  acknowledged: 'Acknowledged',
  resolved: 'Resolved',
  reopened: 'Reopened (the error occurred again)',
  investigated: 'Assistant run started',
}

export const historyLabel = (v) => HISTORY[v] || String(v).replace(/_/g, ' ')

export const DROP_REASON = {
  invalid_schema: 'Invalid event',
  level_below_threshold: 'Below warning level',
  quota: 'Daily limit reached',
  rate_limited: 'Rate limited',
  group_cap: 'Too many different errors',
  too_large: 'Too large',
}

export const dropLabel = (v) => DROP_REASON[v] || String(v).replace(/_/g, ' ')

export const LEVEL_LABEL = { warning: 'Warning', error: 'Error', fatal: 'Fatal' }

export const canRun = (project) => project.your_access === 'run' || project.your_access === 'manage'
export const canManage = (project) => project.your_access === 'manage'

// Ingestion is for people to turn on deliberately: logs can hold personal or secret data.
export const INGEST_WARNING =
  'Application logs can contain personal or secret data. Sentinel redacts known secret shapes before storing events, but redaction is pattern based and can miss unknown ones. Turn this on only for applications whose logs you are allowed to collect.'
