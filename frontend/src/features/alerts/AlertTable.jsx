import { Link } from 'react-router-dom'
import DataTable from '../../components/DataTable.jsx'
import StatusBadge from '../../components/StatusBadge.jsx'
import { EmptyState } from '../../components/states.jsx'
import { formatDateTime } from '../../lib/format.js'
import { ruleLabel, sourceLabel } from './labels.js'

// The alert list. The title is a measured fact (counts and place), never a cause.
export default function AlertTable({ alerts, projectId, emptyText }) {
  return (
    <DataTable
      caption="Alerts"
      rows={alerts}
      getRowKey={(a) => a.id}
      empty={<EmptyState title="No alerts">{emptyText}</EmptyState>}
      columns={[
        { key: 'title', header: 'Alert', render: (a) => <Link to={`/projects/${projectId}/alerts/${a.id}`}>{a.title}</Link> },
        { key: 'rule', header: 'Kind', render: (a) => ruleLabel(a.rule) },
        { key: 'severity', header: 'Severity', render: (a) => <StatusBadge domain="severity" value={a.severity} /> },
        { key: 'status', header: 'Status', render: (a) => <StatusBadge domain="alert" value={a.status} /> },
        { key: 'source', header: 'Source', render: (a) => sourceLabel(a.source) },
        { key: 'seen', header: 'Last seen', render: (a) => formatDateTime(a.last_seen) },
      ]}
    />
  )
}
