import { useState } from 'react'
import Alert from '../../components/Alert.jsx'
import Button from '../../components/Button.jsx'
import DataTable from '../../components/DataTable.jsx'
import { ConfirmDialog } from '../../components/Dialog.jsx'
import { EmptyState } from '../../components/states.jsx'
import { formatDate } from '../../lib/format.js'
import { ANALYSABLE_SOURCE, sourceDetail, sourceTypeLabel } from './labels.js'

export default function SourceList({ sources, onRemove }) {
  const [removing, setRemoving] = useState(null)
  const registeredOnly = sources.some((s) => !ANALYSABLE_SOURCE.has(s.source_type))
  return (
    <>
      {registeredOnly && (
        <Alert tone="info">Git, localhost and remote sources are recorded only. Sentinel AI does not fetch, clone or contact them yet, and cannot analyse them.</Alert>
      )}
      <DataTable
        caption="Project sources"
        rows={sources}
        getRowKey={(s) => s.id}
        empty={<EmptyState title="No sources yet">Add a ZIP upload to analyse the project.</EmptyState>}
        columns={[
          { key: 'name', header: 'Name' },
          { key: 'type', header: 'Type', render: (s) => sourceTypeLabel(s.source_type) },
          { key: 'detail', header: 'Details', render: (s) => <span className="mono">{sourceDetail(s)}</span> },
          { key: 'added', header: 'Added', render: (s) => formatDate(s.created_at) },
          { key: 'actions', header: <span className="visually-hidden">Actions</span>, render: (s) => <Button size="sm" variant="danger" onClick={() => setRemoving(s)} aria-label={`Remove source ${s.name}`}>Remove</Button> },
        ]}
      />
      <ConfirmDialog
        open={Boolean(removing)}
        onClose={() => setRemoving(null)}
        title="Remove this source?"
        confirmLabel="Remove source"
        danger
        onConfirm={async () => {
          await onRemove(removing)
          setRemoving(null)
        }}
      >
        <p>{removing && `"${removing.name}" will no longer be available for analysis. Past analyses and plans are kept.`}</p>
      </ConfirmDialog>
    </>
  )
}
