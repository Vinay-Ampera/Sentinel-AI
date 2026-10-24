import { useState } from 'react'
import Alert from '../../components/Alert.jsx'
import Button from '../../components/Button.jsx'
import Field from '../../components/Field.jsx'
import { describeError } from '../../lib/errors.js'

// Acknowledge means "seen"; resolve closes the alert. Neither changes a finding, a run or any
// test result. The server decides who may do it; this only hides controls that would be refused.
export default function AlertActions({ alert, projectId, api, onChanged }) {
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState(null)

  async function act(kind) {
    setBusy(kind)
    setError(null)
    try {
      const next = kind === 'acknowledge' ? await api.acknowledgeAlert(projectId, alert.id, note.trim()) : await api.resolveAlert(projectId, alert.id, note.trim())
      setNote('')
      onChanged(next)
    } catch (e) {
      setError(e.status === 403 || e.status === 409 || e.status === 422 ? e.message : describeError(e).message)
    } finally {
      setBusy('')
    }
  }

  if (alert.status === 'resolved') return <p className="muted">This alert is resolved. If the error occurs again it is reopened.</p>
  return (
    <div className="alert-actions">
      {error && <Alert tone="danger" title="The change was not recorded">{error}</Alert>}
      <Field label="Note (optional)" value={note} maxLength={1000} onChange={(e) => setNote(e.target.value)} />
      <div className="alert-actions-row">
        {alert.status === 'open' && <Button loading={busy === 'acknowledge'} loadingLabel="Saving…" disabled={Boolean(busy)} onClick={() => act('acknowledge')}>Acknowledge</Button>}
        <Button variant="primary" loading={busy === 'resolve'} loadingLabel="Saving…" disabled={Boolean(busy)} onClick={() => act('resolve')}>Resolve</Button>
      </div>
    </div>
  )
}
