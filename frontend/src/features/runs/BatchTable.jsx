import DataTable from '../../components/DataTable.jsx'
import StatusBadge from '../../components/StatusBadge.jsx'
import { durationBetween, formatDateTime, formatDuration } from '../../lib/format.js'

// How the run was split into units of work. Useful when something retried or failed to start.
export default function BatchTable({ batches }) {
  return (
    <DataTable
      caption="Batches"
      rows={batches}
      getRowKey={(b) => b.id}
      columns={[
        { key: 'n', header: 'Batch', render: (b) => b.ordinal },
        { key: 'status', header: 'Status', render: (b) => <StatusBadge domain="run" value={b.status} /> },
        { key: 'attempt', header: 'Attempt', render: (b) => `${b.attempt} of ${b.max_attempts}` },
        { key: 'started', header: 'Started', render: (b) => (b.started_at ? formatDateTime(b.started_at) : 'Not started') },
        { key: 'duration', header: 'Duration', render: (b) => formatDuration(durationBetween(b.started_at, b.finished_at) ?? undefined) },
        { key: 'error', header: 'Problem', render: (b) => b.error_summary || <span className="muted">None recorded</span> },
      ]}
    />
  )
}
