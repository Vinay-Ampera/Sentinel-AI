import { Link } from 'react-router-dom'
import DataTable from '../../components/DataTable.jsx'
import StatusBadge from '../../components/StatusBadge.jsx'
import { EmptyState } from '../../components/states.jsx'
import { formatDateTime } from '../../lib/format.js'
import { workflowLabel } from './labels.js'

function usage(run) {
  if (run.cache_hit) return 'Reused earlier answer'
  return run.used_llm ? 'Used the model' : 'Built-in only'
}

export default function AgentRunTable({ runs, projectId }) {
  return (
    <DataTable
      caption="Assistant runs"
      rows={runs}
      getRowKey={(r) => r.id}
      empty={<EmptyState title="No assistant runs yet">Ask the assistant to draft a plan, or use it from a finding.</EmptyState>}
      columns={[
        { key: 'workflow', header: 'What', render: (r) => <Link to={`/projects/${projectId}/assistant/${r.id}`}>{workflowLabel(r.workflow)}</Link> },
        { key: 'status', header: 'Outcome', render: (r) => <StatusBadge domain="agent" value={r.status} /> },
        { key: 'model', header: 'Model', render: usage },
        { key: 'when', header: 'Started', render: (r) => formatDateTime(r.started_at) },
      ]}
    />
  )
}
