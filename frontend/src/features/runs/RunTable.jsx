import { useState } from 'react'
import { Link } from 'react-router-dom'
import Button from '../../components/Button.jsx'
import DataTable from '../../components/DataTable.jsx'
import { ConfirmDialog } from '../../components/Dialog.jsx'
import StatusBadge from '../../components/StatusBadge.jsx'
import { EmptyState } from '../../components/states.jsx'
import { durationBetween, formatDateTime, formatDuration } from '../../lib/format.js'
import { ACTIVE_RUN, CANCELLABLE_RUN } from './labels.js'
import './RunTable.css'

// Run history. The list endpoint carries no per-result counts, so counts live on each report.
export default function RunTable({ runs, projectId, planVersions, onCancel }) {
  const [cancelling, setCancelling] = useState(null)
  return (
    <>
      <DataTable
        caption="Run history, newest first"
        rows={runs}
        getRowKey={(r) => r.id}
        empty={<EmptyState title="No runs match" />}
        columns={[
          { key: 'when', header: 'Started', render: (r) => formatDateTime(r.started_at || r.created_at) },
          { key: 'status', header: 'Status', render: (r) => <StatusBadge domain="run" value={r.status} /> },
          { key: 'plan', header: 'Plan', render: (r) => (planVersions[r.plan_id] ? <Link to={`/projects/${projectId}/plans/${r.plan_id}`}>Version {planVersions[r.plan_id]}</Link> : 'Unknown plan') },
          { key: 'duration', header: 'Duration', render: (r) => (ACTIVE_RUN.has(r.status) ? 'In progress' : formatDuration(durationBetween(r.started_at, r.finished_at) ?? undefined)) },
          {
            key: 'actions',
            header: <span className="visually-hidden">Actions</span>,
            render: (r) => (
              <span className="run-actions">
                <Link to={`/projects/${projectId}/runs/${r.id}`}>Open report</Link>
                {CANCELLABLE_RUN.has(r.status) && <Button size="sm" variant="danger" onClick={() => setCancelling(r)}>Cancel run</Button>}
              </span>
            ),
          },
        ]}
      />
      <ConfirmDialog
        open={Boolean(cancelling)}
        onClose={() => setCancelling(null)}
        title="Cancel this run?"
        confirmLabel="Cancel run"
        danger
        onConfirm={async () => {
          await onCancel(cancelling)
          setCancelling(null)
        }}
      >
        <p>Checks that have not started will not run. A check already running is asked to stop.</p>
      </ConfirmDialog>
    </>
  )
}
