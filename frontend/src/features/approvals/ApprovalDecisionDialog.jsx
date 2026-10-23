import { useCallback, useState } from 'react'
import Alert from '../../components/Alert.jsx'
import Button from '../../components/Button.jsx'
import Dialog from '../../components/Dialog.jsx'
import Field from '../../components/Field.jsx'
import KeyValueList from '../../components/KeyValueList.jsx'
import StatusBadge from '../../components/StatusBadge.jsx'
import { DataState } from '../../components/states.jsx'
import { useLoad } from '../../hooks/useLoad.js'
import { describeError } from '../../lib/errors.js'
import { formatDateTime } from '../../lib/format.js'

const HIGH = new Set(['high', 'critical'])

// Decide a target-authorization approval. The server decides who may; this shows what is being
// authorised so the decision is informed, requires the 10-character reason the server asks for
// when approving high or critical risk, and shows the server's refusal if there is one.
export default function ApprovalDecisionDialog({ approval, api, onClose, onDecided }) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)
  const loadAuth = useCallback(() => api.listAuthorizations(approval.project_id), [api, approval.project_id])
  const [auths] = useLoad(loadAuth)

  const needsReason = HIGH.has(approval.risk_level)
  const reasonTooShort = needsReason && reason.trim().length < 10

  async function decide(decision) {
    setBusy(decision)
    setError(null)
    try {
      await api.decideApproval(approval.id, decision, reason.trim() || null)
      await onDecided(decision)
    } catch (e) {
      setError(describeError(e).message)
      setBusy(null)
    }
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title="Target authorization request"
      footer={
        <>
          <Button onClick={onClose} disabled={Boolean(busy)}>Cancel</Button>
          <Button variant="danger" onClick={() => decide('rejected')} loading={busy === 'rejected'} disabled={Boolean(busy)}>Reject</Button>
          <Button
            variant="primary"
            onClick={() => decide('approved')}
            loading={busy === 'approved'}
            disabled={Boolean(busy) || reasonTooShort}
            disabledReason={reasonTooShort ? 'Approving high or critical risk needs a reason of at least 10 characters' : undefined}
          >
            Approve
          </Button>
        </>
      }
    >
      <p>Risk: <StatusBadge domain="risk" value={approval.risk_level} /></p>
      <DataState state={auths} what="this authorization" loadingLabel="Loading details…" isEmpty={() => false}>
        {(items) => {
          const a = items.find((x) => x.id === approval.authorization_id)
          if (!a) return <Alert tone="warning">The authorization details could not be found. Decide only if you can verify the target another way.</Alert>
          const scope = a.scope || {}
          return (
            <KeyValueList
              items={[
                { label: 'Environment', value: a.environment },
                { label: 'Paths', value: Array.isArray(scope.paths) ? scope.paths.join(', ') : null },
                { label: 'Methods', value: Array.isArray(scope.methods) ? scope.methods.join(', ') : null },
                { label: 'Risk levels allowed', value: (a.allowed_risk || []).join(', ') },
                { label: 'Valid until', value: formatDateTime(a.valid_until) },
                { label: 'Justification', value: a.justification },
              ]}
            />
          )
        }}
      </DataState>
      {error && <Alert tone="danger" title="The decision was not recorded">{error}</Alert>}
      <Field
        as="textarea"
        label="Reason"
        hint={needsReason ? 'Required to approve high or critical risk (at least 10 characters).' : 'Optional. Recorded with your decision.'}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        maxLength={2000}
      />
    </Dialog>
  )
}
