import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Alert from '../../components/Alert.jsx'
import Button from '../../components/Button.jsx'
import Card from '../../components/Card.jsx'
import Field from '../../components/Field.jsx'
import { EmptyState } from '../../components/states.jsx'
import { describeError } from '../../lib/errors.js'
import './StartRunCard.css'

// Start a run from an approved plan. The request carries only the plan: what may run, and how
// risky it is, were decided when the plan was approved. One idempotency key per attempt, so a
// double click or a retry returns the original run instead of starting a second one.
export default function StartRunCard({ api, projectId, plans, archived }) {
  const navigate = useNavigate()
  const approved = plans.filter((p) => p.status === 'approved').sort((a, b) => b.version - a.version)
  const [planId, setPlanId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const keyRef = useRef(null)

  async function start() {
    setBusy(true)
    setError(null)
    keyRef.current = keyRef.current || crypto.randomUUID()
    try {
      const run = await api.createRun(projectId, planId, keyRef.current)
      keyRef.current = null
      navigate(`/projects/${projectId}/runs/${run.id}`)
    } catch (e) {
      setError(describeError(e).message)
      setBusy(false)
    }
  }

  return (
    <Card title="Start a run">
      {approved.length === 0 ? (
        <EmptyState title="No approved plan to run yet">Submit a plan and get it approved first. Approving a plan does not run anything.</EmptyState>
      ) : (
        <div className="start-run">
          <Field as="select" label="Plan to run" hint="Only approved plans can be run." value={planId} onChange={(e) => setPlanId(e.target.value)}>
            <option value="">Select an approved plan…</option>
            {approved.map((p) => <option key={p.id} value={p.id}>Version {p.version} · {p.risk_level} risk</option>)}
          </Field>
          <Button variant="primary" onClick={start} loading={busy} loadingLabel="Starting…" disabled={!planId || archived} disabledReason={archived ? 'Archived projects cannot start runs' : 'Choose a plan first'}>
            Start run
          </Button>
        </div>
      )}
      {error && <Alert tone="danger" title="The run was not started">{error}</Alert>}
    </Card>
  )
}
