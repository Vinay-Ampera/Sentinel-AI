import { useState } from 'react'
import Alert from '../../components/Alert.jsx'
import Button from '../../components/Button.jsx'
import Dialog from '../../components/Dialog.jsx'
import Field from '../../components/Field.jsx'
import { describeError } from '../../lib/errors.js'
import './RequestAuthorizationDialog.css'

const METHODS = ['GET', 'HEAD', 'OPTIONS', 'POST', 'PUT', 'PATCH', 'DELETE']
const SAFE = new Set(['GET', 'HEAD', 'OPTIONS'])
const RISKS = ['low', 'medium', 'high']

// Ask for permission to test a target. Nothing is tested by asking: the request waits for an
// eligible approver. Methods that change data are labelled, and the server limits the window.
export default function RequestAuthorizationDialog({ open, onClose, sources, onRequest }) {
  const [sourceId, setSourceId] = useState('')
  const [paths, setPaths] = useState('/')
  const [methods, setMethods] = useState(['GET', 'HEAD', 'OPTIONS'])
  const [risks, setRisks] = useState(['low'])
  const [hours, setHours] = useState('24')
  const [justification, setJustification] = useState('')
  const [touched, setTouched] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const source = sources.find((s) => s.id === sourceId)
  const toggle = (list, setList, v) => setList(list.includes(v) ? list.filter((x) => x !== v) : [...list, v])
  const invalid = {
    source: !sourceId,
    hours: !(Number(hours) >= 1),
    justification: justification.trim().length < 10,
    methods: methods.length === 0,
    risks: risks.length === 0,
  }

  async function submit(event) {
    event.preventDefault()
    setTouched(true)
    if (Object.values(invalid).some(Boolean)) return
    setBusy(true)
    setError(null)
    try {
      await onRequest(sourceId, {
        environment: source.environment || 'local',
        paths: paths.split(/[\s,]+/).filter(Boolean),
        methods,
        allowed_risk: risks,
        valid_until: new Date(Date.now() + Number(hours) * 3600 * 1000).toISOString(),
        justification: justification.trim(),
      })
    } catch (e) {
      setError(describeError(e).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Request target authorization"
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>Cancel</Button>
          <Button type="submit" form="request-auth-form" variant="primary" loading={busy} loadingLabel="Requesting…">Request authorization</Button>
        </>
      }
    >
      <form id="request-auth-form" onSubmit={submit} noValidate>
        <Alert tone="info">Asking does not test anything. An eligible approver must approve it first.</Alert>
        {error && <Alert tone="danger" title="The request was not made">{error}</Alert>}
        <Field as="select" label="Target" value={sourceId} onChange={(e) => setSourceId(e.target.value)} required error={touched && invalid.source ? 'Choose a target.' : undefined} hint={sources.length === 0 ? 'Add a localhost or remote URL source on the Setup tab first.' : source ? `Environment: ${source.environment || 'local'}` : undefined}>
          <option value="">Select…</option>
          {sources.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.target_url})</option>)}
        </Field>
        <Field label="Paths" hint="Space or comma separated, for example / /api" value={paths} onChange={(e) => setPaths(e.target.value)} />
        <fieldset className="auth-checks">
          <legend>HTTP methods</legend>
          {METHODS.map((m) => (
            <label key={m}><input type="checkbox" checked={methods.includes(m)} onChange={() => toggle(methods, setMethods, m)} /> {m}{SAFE.has(m) ? '' : ' (changes data)'}</label>
          ))}
          {touched && invalid.methods && <p className="field-error">Choose at least one method.</p>}
        </fieldset>
        <fieldset className="auth-checks">
          <legend>Risk levels allowed</legend>
          {RISKS.map((r) => <label key={r}><input type="checkbox" checked={risks.includes(r)} onChange={() => toggle(risks, setRisks, r)} /> {r}</label>)}
          {touched && invalid.risks && <p className="field-error">Choose at least one level.</p>}
        </fieldset>
        <Field label="Valid for (hours)" type="number" min="1" max="720" hint="The server limits how long a window may be." value={hours} onChange={(e) => setHours(e.target.value)} error={touched && invalid.hours ? 'Enter a number of hours.' : undefined} />
        <Field as="textarea" label="Why is this needed?" hint="At least 10 characters. Approvers read this." value={justification} onChange={(e) => setJustification(e.target.value)} maxLength={2000} required error={touched && invalid.justification ? 'Write at least 10 characters.' : undefined} />
      </form>
    </Dialog>
  )
}
