import { Link } from 'react-router-dom'
import Card from '../../components/Card.jsx'
import DataTable from '../../components/DataTable.jsx'
import StatusBadge from '../../components/StatusBadge.jsx'
import { EmptyState } from '../../components/states.jsx'
import { formatDateTime } from '../../lib/format.js'
import { workflowLabel } from '../assistant/labels.js'

// One trace id: the platform workflows that carry it and the events the application reported
// with it. They are listed together because they share an identifier, not because one caused
// the other.
export default function TraceView({ trace, projectId }) {
  return (
    <>
      <Card title="Workflows with this trace id" headingLevel={3}>
        {trace.runs.length === 0 && trace.assistant_runs.length === 0 ? (
          <p className="muted">No test run or assistant run of this project has this trace id; only reported events do.</p>
        ) : (
          <ul>
            {trace.runs.map((r) => (
              <li key={r.id}><Link to={`/projects/${projectId}/runs/${r.id}`}>Test run</Link> <StatusBadge domain="run" value={r.status} /> · {formatDateTime(r.created_at)}</li>
            ))}
            {trace.assistant_runs.map((a) => (
              <li key={a.id}>
                <Link to={`/projects/${projectId}/assistant/${a.id}`}>{workflowLabel(a.workflow)}</Link> <StatusBadge domain="agent" value={a.status} /> · {a.steps.length} steps
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card title="Reported events with this trace id" headingLevel={3}>
        <DataTable
          caption="Events in this trace"
          rows={trace.events}
          getRowKey={(e) => e.id}
          empty={<EmptyState title="No events">The application has not reported events with this trace id (or the samples expired).</EmptyState>}
          columns={[
            { key: 'received_at', header: 'Received', render: (e) => formatDateTime(e.received_at) },
            { key: 'service', header: 'Service' },
            { key: 'level', header: 'Level' },
            { key: 'message', header: 'Message (as reported, redacted)' },
          ]}
        />
      </Card>
      <ul className="muted">{trace.limits.map((l) => <li key={l}>{l}</li>)}</ul>
    </>
  )
}
