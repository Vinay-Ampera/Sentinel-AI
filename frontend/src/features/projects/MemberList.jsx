import { useState } from 'react'
import Button from '../../components/Button.jsx'
import DataTable from '../../components/DataTable.jsx'
import { ConfirmDialog } from '../../components/Dialog.jsx'
import { EmptyState } from '../../components/states.jsx'
import { ACCESS_LEVELS } from './labels.js'

// The server decides who may change access; the select only offers the three levels it knows.
export default function MemberList({ members, onChangeLevel, onRemove }) {
  const [removing, setRemoving] = useState(null)
  return (
    <>
      <DataTable
        caption="Project members"
        rows={members}
        getRowKey={(m) => m.user_id}
        empty={<EmptyState title="No other members">The project owner always has full access. Add people who should see or run this project.</EmptyState>}
        columns={[
          { key: 'who', header: 'Member', render: (m) => <><strong>{m.display_name}</strong><br /><span className="muted">{m.email}</span></> },
          {
            key: 'level',
            header: 'Access',
            render: (m) => (
              <select aria-label={`Access level for ${m.display_name}`} value={m.access_level} onChange={(e) => onChangeLevel(m, e.target.value)}>
                {Object.entries(ACCESS_LEVELS).map(([value, a]) => <option key={value} value={value}>{a.label}</option>)}
              </select>
            ),
          },
          { key: 'actions', header: <span className="visually-hidden">Actions</span>, render: (m) => <Button size="sm" variant="danger" onClick={() => setRemoving(m)} aria-label={`Remove ${m.display_name}`}>Remove</Button> },
        ]}
      />
      <ConfirmDialog
        open={Boolean(removing)}
        onClose={() => setRemoving(null)}
        title="Remove this member?"
        confirmLabel="Remove member"
        danger
        onConfirm={async () => {
          await onRemove(removing)
          setRemoving(null)
        }}
      >
        <p>{removing && `${removing.display_name} will lose access to this project.`}</p>
      </ConfirmDialog>
    </>
  )
}
