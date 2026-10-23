import { useState } from 'react'
import Button from '../../components/Button.jsx'
import DataTable from '../../components/DataTable.jsx'
import { ConfirmDialog } from '../../components/Dialog.jsx'
import { formatDateTime } from '../../lib/format.js'

// Your active sign-ins. The current one is marked and has no revoke button (use Sign out).
export default function SessionList({ sessions, onRevoke }) {
  const [revoking, setRevoking] = useState(null)
  return (
    <>
      <DataTable
        caption="Your signed-in sessions"
        rows={sessions}
        getRowKey={(s) => s.id}
        columns={[
          { key: 'device', header: 'Device', render: (s) => <>{s.user_agent || 'Unknown device'}{s.current && <strong> (this session)</strong>}</> },
          { key: 'ip', header: 'Address', render: (s) => s.ip_address || 'Not recorded' },
          { key: 'started', header: 'Signed in', render: (s) => formatDateTime(s.created_at) },
          { key: 'seen', header: 'Last active', render: (s) => formatDateTime(s.last_seen_at) },
          { key: 'action', header: <span className="visually-hidden">Action</span>, render: (s) => (s.current ? null : <Button size="sm" variant="danger" onClick={() => setRevoking(s)} aria-label={`Sign out session started ${formatDateTime(s.created_at)}`}>Sign out</Button>) },
        ]}
      />
      <ConfirmDialog
        open={Boolean(revoking)}
        onClose={() => setRevoking(null)}
        title="Sign out this session?"
        confirmLabel="Sign out session"
        danger
        onConfirm={async () => {
          await onRevoke(revoking)
          setRevoking(null)
        }}
      >
        <p>The device will need to sign in again.</p>
      </ConfirmDialog>
    </>
  )
}
