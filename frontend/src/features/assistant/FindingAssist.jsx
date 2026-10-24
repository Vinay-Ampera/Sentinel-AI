import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Alert from '../../components/Alert.jsx'
import Button from '../../components/Button.jsx'
import Card from '../../components/Card.jsx'
import { describeError } from '../../lib/errors.js'
import './FindingAssist.css'

// Two assistant actions for one finding. They only start a run and open its result.
export default function FindingAssist({ projectId, findingId, api }) {
  const navigate = useNavigate()
  const [busy, setBusy] = useState('')
  const [error, setError] = useState(null)

  async function start(workflow) {
    setBusy(workflow)
    setError(null)
    try {
      const run = await api.createAgentRun(projectId, { workflow, finding_id: findingId })
      navigate(`/projects/${projectId}/assistant/${run.id}`)
    } catch (e) {
      setError(e.status === 403 || e.status === 409 || e.status === 422 || e.status === 429 ? e.message : describeError(e).message)
      setBusy('')
    }
  }

  return (
    <Card title="Assistant">
      {error && <Alert tone="danger" title="The request was not made">{error}</Alert>}
      <p className="muted">Suggestions only. A drafted test needs you to have marked the finding likely or confirmed first, and it is never added to your project automatically.</p>
      <div className="finding-assist-actions">
        <Button loading={busy === 'investigation'} loadingLabel="Investigating…" disabled={Boolean(busy)} onClick={() => start('investigation')}>Investigate</Button>
        <Button loading={busy === 'regression'} loadingLabel="Drafting…" disabled={Boolean(busy)} onClick={() => start('regression')}>Draft a regression test</Button>
      </div>
    </Card>
  )
}
