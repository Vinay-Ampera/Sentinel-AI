import { Link } from 'react-router-dom'
import Card from '../../components/Card.jsx'
import KeyValueList from '../../components/KeyValueList.jsx'
import StatusBadge from '../../components/StatusBadge.jsx'
import { formatDateTime } from '../../lib/format.js'
import { causeLabel, historyLabel, ruleLabel, sourceLabel } from './labels.js'
import './AlertDetailView.css'

const show = (v) => (typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v))

// What was measured, when, where, with the evidence references and the standing statement
// that no cause is known. Nothing here is a root cause.
export default function AlertDetailView({ alert, projectId }) {
  const measured = Object.entries(alert.measured || {}).filter(([, v]) => v !== null && v !== undefined)
  return (
    <>
      <Card title="What was measured" headingLevel={3}>
        <KeyValueList
          items={[
            { label: 'Kind', value: ruleLabel(alert.rule) },
            { label: 'Severity', value: <StatusBadge domain="severity" value={alert.severity} /> },
            { label: 'Status', value: <StatusBadge domain="alert" value={alert.status} /> },
            { label: 'Source', value: sourceLabel(alert.source) },
            { label: 'Confidence', value: 'Observed: counts and times measured by Sentinel' },
            { label: 'First seen', value: formatDateTime(alert.first_seen) },
            { label: 'Last seen', value: formatDateTime(alert.last_seen) },
            { label: 'Occurrences counted on this alert', value: String(alert.occurrences) },
          ]}
        />
        {measured.length > 0 && (
          <ul className="alert-measured" aria-label="Measurements">
            {measured.map(([k, v]) => <li key={k}><span className="mono">{k.replace(/_/g, ' ')}</span>: {show(v)}</li>)}
          </ul>
        )}
      </Card>
      <Card title="Evidence and likely cause" headingLevel={3}>
        <p><strong>Cause:</strong> {causeLabel(alert.cause_status)}</p>
        <p className="muted">{alert.cause_note}</p>
        <ul className="alert-links">
          {alert.run_id && <li><Link to={`/projects/${projectId}/runs/${alert.run_id}`}>Open the run</Link></li>}
          {alert.run_id && alert.result_id && <li><Link to={`/projects/${projectId}/runs/${alert.run_id}/results/${alert.result_id}`}>Open the failed result</Link></li>}
          {alert.finding_id && <li><Link to={`/projects/${projectId}/findings/${alert.finding_id}`}>Open the finding</Link></li>}
          {alert.agent_run_id && <li><Link to={`/projects/${projectId}/assistant/${alert.agent_run_id}`}>Open the assistant's investigation</Link></li>}
        </ul>
        <p><strong>Suggested next step:</strong> {alert.next_action}</p>
      </Card>
      <Card title="History" headingLevel={3}>
        <ol className="alert-history">
          {alert.history.map((h, i) => (
            <li key={`${h.action}-${h.created_at}-${i}`}>
              <strong>{historyLabel(h.action)}</strong> · {formatDateTime(h.created_at)}
              {h.actor_user_id ? '' : ' · by Sentinel'}
              {h.note ? `: ${h.note}` : ''}
            </li>
          ))}
        </ol>
      </Card>
    </>
  )
}
