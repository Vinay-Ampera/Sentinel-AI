import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import Alert from '../../components/Alert.jsx'
import Button from '../../components/Button.jsx'
import Card from '../../components/Card.jsx'
import { describeError } from '../../lib/errors.js'
import './AlertAssist.css'

// The failure-to-test loop. A person starts it; nothing calls a model because an alert fired.
// It opens an assistant run, whose result is suggestions only: a drafted test is stored text
// for review and is never added to the project, committed or run.
export default function AlertAssist({ projectId, alert, api }) {
  const navigate = useNavigate()
  const [busy, setBusy] = useState('')
  const [error, setError] = useState(null)

  async function start(workflow) {
    setBusy(workflow)
    setError(null)
    try {
      const run = await api.createAgentRun(projectId, { workflow, alert_id: alert.id })
      navigate(`/projects/${projectId}/assistant/${run.id}`)
    } catch (e) {
      setError(e.status === 403 || e.status === 404 || e.status === 409 || e.status === 422 || e.status === 429 ? e.message : describeError(e).message)
      setBusy('')
    }
  }

  return (
    <Card title="Investigate and draft a test" headingLevel={3}>
      {error && <Alert tone="danger" title="The request was not made">{error}</Alert>}
      <p className="muted">
        Suggestions only, built from the redacted samples above. A test can be drafted only when the reported events carry an error type and a stack trace (or the alert points at a failed test), occurred at least twice, and the project has an analysed source with a supported test framework. If something is missing, the result says what.
      </p>
      <div className="alert-assist-actions">
        <Button loading={busy === 'investigation'} loadingLabel="Investigating…" disabled={Boolean(busy)} onClick={() => start('investigation')}>Investigate</Button>
        <Button loading={busy === 'regression'} loadingLabel="Drafting…" disabled={Boolean(busy)} onClick={() => start('regression')}>Draft a regression test</Button>
      </div>
      {alert.proposal_ids && alert.proposal_ids.length > 0 && (
        <p>{alert.proposal_ids.length} drafted test{alert.proposal_ids.length === 1 ? '' : 's'} came from this alert. <Link to={`/projects/${projectId}/proposals`}>Review on the Proposals tab</Link>.</p>
      )}
    </Card>
  )
}
