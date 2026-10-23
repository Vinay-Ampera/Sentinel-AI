import { useState } from 'react'
import Button from '../../components/Button.jsx'
import DataTable from '../../components/DataTable.jsx'
import { ConfirmDialog } from '../../components/Dialog.jsx'
import StatusBadge from '../../components/StatusBadge.jsx'
import { EmptyState } from '../../components/states.jsx'
import { formatDateTime } from '../../lib/format.js'

const REVOCABLE = new Set(['pending', 'approved'])

// Permission to test a specific target, within a scope and a time window. "In effect" is
// computed by the server from status and window; a pending request is not permission.
export default function AuthorizationList({ authorizations, sourceNames, onRevoke }) {
  const [revoking, setRevoking] = useState(null)
  return (
    <>
      <DataTable
        caption="Target authorizations"
        rows={authorizations}
        getRowKey={(a) => a.id}
        empty={<EmptyState title="No authorizations">Testing a remote or localhost target needs an approved authorization. None has been requested.</EmptyState>}
        columns={[
          { key: 'target', header: 'Target', render: (a) => sourceNames[a.source_id] || 'Unknown source' },
          { key: 'env', header: 'Environment', render: (a) => a.environment },
          { key: 'scope', header: 'Scope', render: (a) => <span className="mono">{[(a.scope.paths || []).join(' '), (a.scope.methods || []).join(' ')].filter(Boolean).join(' · ')}</span> },
          { key: 'risk', header: 'Risk allowed', render: (a) => (a.allowed_risk || []).join(', ') },
          { key: 'status', header: 'Status', render: (a) => <><StatusBadge domain="approval" value={a.status} />{a.in_effect && <><br /><span className="muted">In effect now</span></>}</> },
          { key: 'window', header: 'Valid', render: (a) => (a.valid_until ? `until ${formatDateTime(a.valid_until)}` : 'Not set') },
          { key: 'action', header: <span className="visually-hidden">Action</span>, render: (a) => (REVOCABLE.has(a.status) ? <Button size="sm" variant="danger" onClick={() => setRevoking(a)} aria-label={`Revoke authorization for ${sourceNames[a.source_id] || 'source'}`}>Revoke</Button> : null) },
        ]}
      />
      <ConfirmDialog
        open={Boolean(revoking)}
        onClose={() => setRevoking(null)}
        title="Revoke this authorization?"
        confirmLabel="Revoke"
        danger
        onConfirm={async () => {
          await onRevoke(revoking)
          setRevoking(null)
        }}
      >
        <p>Testing that target will stop being permitted straight away. Runs already finished are kept.</p>
      </ConfirmDialog>
    </>
  )
}
