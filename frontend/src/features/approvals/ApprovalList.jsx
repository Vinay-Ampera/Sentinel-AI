import { Link } from 'react-router-dom'
import Button from '../../components/Button.jsx'
import DataTable from '../../components/DataTable.jsx'
import StatusBadge from '../../components/StatusBadge.jsx'
import { formatDateTime } from '../../lib/format.js'

// Plans are reviewed on their own page (you should read the checks before approving), so a
// plan row links there. Target authorizations are decided here, in a dialog that shows the target.
export default function ApprovalList({ approvals, projectNames, onDecide }) {
  return (
    <DataTable
      caption="Approvals"
      rows={approvals}
      getRowKey={(a) => a.id}
      columns={[
        { key: 'kind', header: 'Request', render: (a) => (a.kind === 'plan' ? 'Test plan' : 'Target authorization') },
        { key: 'project', header: 'Project', render: (a) => projectNames[a.project_id] || 'Unknown project' },
        { key: 'risk', header: 'Risk', render: (a) => <StatusBadge domain="risk" value={a.risk_level} /> },
        { key: 'decision', header: 'Status', render: (a) => <StatusBadge domain="approval" value={a.decision} /> },
        { key: 'when', header: 'Date', render: (a) => (a.decided_at ? `Decided ${formatDateTime(a.decided_at)}` : `Requested ${formatDateTime(a.created_at)}`) },
        { key: 'reason', header: 'Reason', render: (a) => a.reason || <span className="muted">None recorded</span> },
        {
          key: 'action',
          header: <span className="visually-hidden">Action</span>,
          render: (a) => {
            if (a.decision !== 'pending') return null
            return a.kind === 'plan' ? (
              <Link to={`/projects/${a.project_id}/plans/${a.plan_id}`}>Review plan</Link>
            ) : (
              <Button size="sm" variant="primary" onClick={() => onDecide(a)}>Decide</Button>
            )
          },
        },
      ]}
    />
  )
}
