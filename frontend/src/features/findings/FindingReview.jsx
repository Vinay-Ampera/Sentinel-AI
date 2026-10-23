import { useState } from 'react'
import Alert from '../../components/Alert.jsx'
import Button from '../../components/Button.jsx'
import Field from '../../components/Field.jsx'
import { describeError } from '../../lib/errors.js'
import './FindingReview.css'
import { MANUAL_VERIFICATION, NEXT_STATUS, NOTE_STATUSES, statusLabel, verificationLabel } from './labels.js'

// Triage controls. Which transitions are offered mirrors the server's rules as a convenience;
// the server enforces them (and who may decide risk) and its refusal is shown unchanged.
export default function FindingReview({ finding, api, onChanged }) {
  const [status, setStatus] = useState('')
  const [statusNote, setStatusNote] = useState('')
  const [state, setState] = useState('')
  const [stateNote, setStateNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function act(fn) {
    setBusy(true)
    setError(null)
    try {
      const updated = await fn()
      setStatus('')
      setStatusNote('')
      setState('')
      setStateNote('')
      onChanged(updated)
    } catch (e) {
      setError(e.status === 403 || e.status === 409 || e.status === 422 ? e.message : describeError(e).message)
    } finally {
      setBusy(false)
    }
  }

  const options = NEXT_STATUS[finding.status] || []
  const needsReason = NOTE_STATUSES.has(status)
  return (
    <div className="finding-review">
      {error && <Alert tone="danger" title="That change was not made">{error}</Alert>}
      <div className="finding-review-row">
        <Field as="select" label="Change status" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Choose…</option>
          {options.map((s) => <option key={s} value={s}>{statusLabel(s)}</option>)}
        </Field>
        {needsReason && <Field label="Reason" hint="Required. Only administrators may decide this." value={statusNote} onChange={(e) => setStatusNote(e.target.value)} />}
        <Button variant="primary" disabled={!status || busy || (needsReason && !statusNote.trim())} disabledReason={!status ? 'Choose a status first' : 'Enter a reason'} onClick={() => act(() => api.setFindingStatus(finding.id, status, statusNote.trim()))}>
          Apply status
        </Button>
      </div>
      <div className="finding-review-row">
        <Field as="select" label="My verification judgement" hint="Scanner output stays unverified until a person records a judgement." value={state} onChange={(e) => setState(e.target.value)}>
          <option value="">Choose…</option>
          {MANUAL_VERIFICATION.map((s) => <option key={s} value={s}>{verificationLabel(s)}</option>)}
        </Field>
        <Field label="Note" hint="At least 10 characters: what you checked." value={stateNote} onChange={(e) => setStateNote(e.target.value)} />
        <Button variant="primary" disabled={!state || stateNote.trim().length < 10 || busy} disabledReason={!state ? 'Choose a judgement first' : 'Write a note of at least 10 characters'} onClick={() => act(() => api.setFindingVerification(finding.id, state, stateNote.trim()))}>
          Record judgement
        </Button>
      </div>
    </div>
  )
}
