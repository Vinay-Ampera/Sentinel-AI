import { useState } from 'react'
import { Link } from 'react-router-dom'
import Alert from '../../components/Alert.jsx'
import Button from '../../components/Button.jsx'
import Card from '../../components/Card.jsx'
import Field from '../../components/Field.jsx'
import KeyValueList from '../../components/KeyValueList.jsx'
import StatusBadge from '../../components/StatusBadge.jsx'
import { describeError } from '../../lib/errors.js'
import { formatDateTime } from '../../lib/format.js'
import './ProposalCard.css'

// One drafted regression test. The code is shown as text only. Accepting or rejecting records
// a decision; Sentinel never writes the file into the project, commits it or runs it.
export default function ProposalCard({ proposal, canDecide, api, projectId, onChanged }) {
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function decide(decision) {
    setBusy(true)
    setError(null)
    try {
      onChanged(await api.decideRegressionProposal(projectId, proposal.id, decision, note.trim()))
      setNote('')
    } catch (e) {
      setError(e.status === 403 || e.status === 409 || e.status === 422 ? e.message : describeError(e).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card title={proposal.title} headingLevel={3} actions={<StatusBadge domain="proposal" value={proposal.status} />}>
      {error && <Alert tone="danger" title="The decision was not recorded">{error}</Alert>}
      {proposal.risk_flags.length > 0 && (
        <Alert tone="warning" title="Review before accepting">
          The draft uses: {proposal.risk_flags.join(', ')}. A test that does this can reach beyond itself.
        </Alert>
      )}
      <KeyValueList
        items={[
          { label: 'Suggested file', value: <span className="mono">{proposal.target_path}</span> },
          { label: 'Framework', value: proposal.framework },
          { label: 'Why', value: proposal.rationale },
          { label: 'Expected behaviour', value: proposal.expected_behavior },
          { label: 'Based on', value: proposal.evidence_ids.join(', ') || 'Not recorded' },
          ...(proposal.alert_id ? [{ label: 'Drafted from', value: <Link to={`/projects/${projectId}/alerts/${proposal.alert_id}`}>the alert</Link> }] : []),
          ...(proposal.overlap.length > 0 ? [{ label: 'Same name as existing tests', value: proposal.overlap.join(', ') }] : []),
          { label: 'Drafted', value: formatDateTime(proposal.created_at) },
          ...(proposal.decided_at ? [{ label: 'Decision', value: `${proposal.status} on ${formatDateTime(proposal.decided_at)}${proposal.decision_note ? `: ${proposal.decision_note}` : ''}` }] : []),
        ]}
      />
      <pre className="proposal-code" tabIndex={0} aria-label={`Drafted test code for ${proposal.title}`}>{proposal.code}</pre>
      {proposal.status === 'proposed' && canDecide && (
        <div className="proposal-decision">
          <Field label="Note (optional)" value={note} maxLength={1000} onChange={(e) => setNote(e.target.value)} />
          <Button variant="primary" disabled={busy} onClick={() => decide('accepted')}>Accept</Button>
          <Button disabled={busy} onClick={() => decide('rejected')}>Reject</Button>
        </div>
      )}
    </Card>
  )
}
