import { useState } from 'react'
import Alert from '../../components/Alert.jsx'
import Button from '../../components/Button.jsx'
import DataTable from '../../components/DataTable.jsx'
import { ConfirmDialog } from '../../components/Dialog.jsx'
import Field from '../../components/Field.jsx'
import { EmptyState } from '../../components/states.jsx'
import { describeError } from '../../lib/errors.js'
import { formatDateTime } from '../../lib/format.js'

// Emergency, read-only, time-limited access for a super admin; every grant is recorded with its
// reason. Everyone who manages the project can see who had it and why. The server decides who
// may grant; the form is only shown to super admins as a convenience.
export default function BreakGlassPanel({ grants, canGrant, onGrant, onRevoke }) {
  const [justification, setJustification] = useState('')
  const [minutes, setMinutes] = useState('60')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [revoking, setRevoking] = useState(null)

  async function grant(event) {
    event.preventDefault()
    if (!justification.trim()) return
    setBusy(true)
    setError(null)
    try {
      await onGrant(justification.trim(), Number(minutes))
      setJustification('')
    } catch (e) {
      setError(describeError(e).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <DataTable
        caption="Break-glass access"
        rows={grants}
        getRowKey={(g) => g.id}
        empty={<EmptyState title="No emergency access has been used on this project" />}
        columns={[
          { key: 'why', header: 'Reason', render: (g) => g.justification },
          { key: 'when', header: 'Granted', render: (g) => formatDateTime(g.created_at) },
          { key: 'until', header: 'Expires', render: (g) => formatDateTime(g.expires_at) },
          { key: 'state', header: 'State', render: (g) => (g.revoked_at ? 'Revoked' : g.active ? 'Active now' : 'Expired') },
          { key: 'action', header: <span className="visually-hidden">Action</span>, render: (g) => (g.active && !g.revoked_at ? <Button size="sm" variant="danger" onClick={() => setRevoking(g)} aria-label="Revoke emergency access">Revoke</Button> : null) },
        ]}
      />
      {canGrant && (
        <form onSubmit={grant} noValidate className="break-glass-form" aria-labelledby="bg-title">
          <h3 id="bg-title">Grant emergency access</h3>
          <Alert tone="warning">Read-only and temporary. The reason you give is recorded and shown to project managers.</Alert>
          {error && <Alert tone="danger">{error}</Alert>}
          <Field as="textarea" label="Reason" required value={justification} onChange={(e) => setJustification(e.target.value)} maxLength={2000} />
          <Field label="Minutes" type="number" min="1" max="1000" value={minutes} onChange={(e) => setMinutes(e.target.value)} />
          <Button type="submit" variant="primary" loading={busy} loadingLabel="Granting…" disabled={!justification.trim()} disabledReason="Enter a reason">Grant access</Button>
        </form>
      )}
      <ConfirmDialog
        open={Boolean(revoking)}
        onClose={() => setRevoking(null)}
        title="Revoke emergency access?"
        confirmLabel="Revoke"
        danger
        onConfirm={async () => {
          await onRevoke(revoking)
          setRevoking(null)
        }}
      >
        <p>The access ends immediately.</p>
      </ConfirmDialog>
    </>
  )
}
