import { Link } from 'react-router-dom'
import DataTable from '../../components/DataTable.jsx'
import StatusBadge from '../../components/StatusBadge.jsx'
import { formatDateTime } from '../../lib/format.js'

export default function PlanList({ plans, projectId }) {
  const sorted = [...plans].sort((a, b) => b.version - a.version)
  return (
    <DataTable
      caption="Test plans, newest version first"
      rows={sorted}
      getRowKey={(p) => p.id}
      columns={[
        { key: 'version', header: 'Plan', render: (p) => <Link to={`/projects/${projectId}/plans/${p.id}`}>Version {p.version}</Link> },
        { key: 'status', header: 'Status', render: (p) => <StatusBadge domain="plan" value={p.status} /> },
        { key: 'risk', header: 'Highest risk', render: (p) => <StatusBadge domain="risk" value={p.risk_level} /> },
        { key: 'mode', header: 'How it was made', render: (p) => p.mode.replace(/_/g, ' ') },
        { key: 'created', header: 'Created', render: (p) => formatDateTime(p.created_at) },
      ]}
    />
  )
}
