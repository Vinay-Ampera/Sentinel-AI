import { useState } from 'react'
import Alert from '../../components/Alert.jsx'
import Button from '../../components/Button.jsx'
import { describeError } from '../../lib/errors.js'
import './PolicyEditor.css'

const LEVELS = ['low', 'medium', 'high', 'critical']
const ROLES = ['developer', 'admin', 'super_admin']

// Edits one policy value: a set of risk levels, a set of roles, or an on/off flag. The server
// validates the value (and who may change it) and its message is shown if it refuses; the UI
// only offers the choices the server accepts.
// kind: 'levels' | 'roles' | 'flag'. For a flag the value is { allowed: boolean }.
export default function PolicyEditor({ legend, help, kind, value, onSave }) {
  const initial = kind === 'flag' ? Boolean(value && value.allowed) : [...(value || [])]
  const [draft, setDraft] = useState(initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [saved, setSaved] = useState(false)

  const options = kind === 'roles' ? ROLES : LEVELS
  const changed = kind === 'flag' ? draft !== initial : JSON.stringify([...draft].sort()) !== JSON.stringify([...initial].sort())

  function toggle(option) {
    setSaved(false)
    setDraft((d) => (d.includes(option) ? d.filter((x) => x !== option) : [...d, option]))
  }

  async function save() {
    setBusy(true)
    setError(null)
    try {
      await onSave(kind === 'flag' ? { allowed: draft } : options.filter((o) => draft.includes(o)))
      setSaved(true)
    } catch (e) {
      setError(describeError(e).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <fieldset className="policy-editor">
      <legend>{legend}</legend>
      {help && <p className="muted">{help}</p>}
      {error && <Alert tone="danger" title="The policy was not changed">{error}</Alert>}
      {saved && !changed && <Alert tone="success">Saved.</Alert>}
      {kind === 'flag' ? (
        <label className="policy-option">
          <input type="checkbox" checked={draft} onChange={(e) => { setSaved(false); setDraft(e.target.checked) }} /> Allowed
        </label>
      ) : (
        <div className="policy-options">
          {options.map((o) => (
            <label key={o} className="policy-option">
              <input type="checkbox" checked={draft.includes(o)} onChange={() => toggle(o)} /> {o.replace('_', ' ')}
            </label>
          ))}
        </div>
      )}
      <Button size="sm" variant="primary" onClick={save} loading={busy} loadingLabel="Saving…" disabled={!changed} disabledReason="Nothing has changed">Save</Button>
    </fieldset>
  )
}
