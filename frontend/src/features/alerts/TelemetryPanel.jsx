import Alert from '../../components/Alert.jsx'
import Card from '../../components/Card.jsx'
import KeyValueList from '../../components/KeyValueList.jsx'
import { formatDateTime } from '../../lib/format.js'
import { dropLabel, LEVEL_LABEL } from './labels.js'
import './TelemetryPanel.css'

function counts(map, label = (k) => k) {
  const entries = Object.entries(map || {})
  return entries.length ? entries.map(([k, n]) => `${label(k)}: ${n}`).join(', ') : 'None'
}

function modelUsageRows(m) {
  return [
    {
      label: 'Model use in the last 24 hours (estimated)',
      value: `${m.calls} calls (${m.failed} failed, ${m.blocked_by_budget} blocked by budget), ${m.retries} retries, ${m.input_tokens} input and ${m.output_tokens} output tokens, about $${m.estimated_cost_usd.toFixed(2)}. Cost is an estimate from tokens and configured prices.`,
    },
    { label: 'Incomplete model call records', value: String(m.incomplete_calls) },
    { label: 'Assistant workflows in the last 24 hours', value: `${m.assistant_runs} runs, ${m.workflow_steps} steps (${m.model_steps} used the model)` },
  ]
}

const thresholdText = (t) => Object.entries(t).map(([k, v]) => `${k.replace(/_/g, ' ')}: ${v}`).join(', ')

// What Sentinel did and did not receive, so an empty list is never read as "healthy".
export default function TelemetryPanel({ telemetry }) {
  const t = telemetry
  return (
    <Card title="What Sentinel can see" headingLevel={3}>
      {!t.has_events && (
        <Alert tone="warning" title="No application events have been received">
          {t.ingest_enabled
            ? 'Ingestion is on but nothing has arrived yet. A quiet alert list does not mean the application is healthy.'
            : 'Event ingestion is off for this project, so application errors are not visible here. Test runs and findings still raise alerts.'}
        </Alert>
      )}
      <KeyValueList
        items={[
          { label: 'Event ingestion', value: t.ingest_enabled ? 'On' : 'Off' },
          { label: 'Active ingest keys', value: String(t.active_keys) },
          { label: 'Last event received', value: t.last_event_at ? formatDateTime(t.last_event_at) : null },
          { label: 'Events in the last 24 hours, by level', value: counts(t.events_last_24h_by_level, (k) => LEVEL_LABEL[k] || k) },
          { label: 'By environment', value: counts(t.events_last_24h_by_environment) },
          { label: 'Refused in the last 24 hours', value: counts(t.dropped_last_24h, dropLabel) },
          { label: 'Alert rule errors in the last 24 hours', value: String(t.evaluation_errors_last_24h ?? 0) },
          { label: 'Error groups with a stack trace', value: `${Math.round((t.share_of_groups_with_stack || 0) * 100)}% of ${t.groups}` },
          { label: 'Samples carrying a trace id', value: String(t.samples_with_trace_id) },
          { label: 'Samples linked to a run, result, finding or trace (verified)', value: String(t.samples_with_verified_link) },
          ...(t.model_usage ? modelUsageRows(t.model_usage) : []),
          ...(t.thresholds ? [{ label: 'Alert thresholds in effect', value: thresholdText(t.thresholds) }] : []),
        ]}
      />
      <p className="telemetry-limits-title"><strong>Limits</strong></p>
      <ul className="telemetry-limits">
        {t.limits.map((l) => <li key={l}>{l}</li>)}
      </ul>
    </Card>
  )
}
