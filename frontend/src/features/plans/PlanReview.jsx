import { useEffect, useState } from 'react'
import { GROUPS, TEST_STATUS, planStatusLabel, statusLabel } from './labels.js'
import './plans.css'

function TestRow({ test, editable, onRemove, busy }) {
  const info = TEST_STATUS[test.status]
  return (
    <li className={`test test-${test.status}`}>
      <div className="test-head">
        <strong>{test.name}</strong>
        <span className={`badge risk-${test.risk_level}`}>Risk: {test.risk_level}</span>
        <span className={`badge status-${test.status}`} title={info ? info.note : ''}>{statusLabel(test.status)}</span>
        {test.requires_approval && <span className="badge needs-approval">Needs approval</span>}
        {editable && (
          <button type="button" onClick={() => onRemove(test.id)} disabled={busy} aria-label={`Remove ${test.name}`}>
            Remove
          </button>
        )}
      </div>
      <p className="reason">{test.rationale}</p>
      <details>
        <summary>Prerequisites and expected evidence</summary>
        <p>Tool: {test.tool} · Category: {test.category} · Origin: {test.origin.replace('_', ' ')}</p>
        {test.target && <p>Target: {test.target.name} ({test.target.source_type.replace('_', ' ')})</p>}
        <p>Prerequisites</p>
        <ul>{test.prerequisites.length ? test.prerequisites.map((p) => <li key={p}>{p}</li>) : <li>None listed</li>}</ul>
        <p>Expected evidence</p>
        <ul>{test.expected_evidence.length ? test.expected_evidence.map((p) => <li key={p}>{p}</li>) : <li>None listed</li>}</ul>
      </details>
    </li>
  )
}

/**
 * Plan review. Buttons are shown from the plan's status and the signed-in role as a
 * convenience only; the server enforces every rule and its message is shown on refusal.
 */
export default function PlanReview({ api, planId, user, onChanged }) {
  const [result, setResult] = useState({ key: null, plan: null, error: null })
  const [tick, setTick] = useState(0)
  const [busy, setBusy] = useState(false)
  const [reason, setReason] = useState('')
  const [actionError, setActionError] = useState(null)

  const key = `${planId}:${tick}`
  useEffect(() => {
    let live = true
    api
      .getPlan(planId)
      .then((plan) => live && setResult({ key, plan, error: null }))
      .catch((e) => live && setResult({ key, plan: null, error: e.message }))
    return () => {
      live = false
    }
  }, [api, planId, key])

  const load = () => setTick((t) => t + 1)
  const fresh = result.key === key
  const plan = result.plan
  const error = fresh ? result.error : null
  const setPlan = (next) => setResult({ key, plan: next, error: null })

  async function act(fn) {
    setBusy(true)
    setActionError(null)
    try {
      setPlan(await fn())
      if (onChanged) onChanged()
    } catch (e) {
      setActionError(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function decide(decision) {
    setBusy(true)
    setActionError(null)
    try {
      await api.decideApproval(plan.approval.id, decision, reason.trim() || null)
      setReason('')
      await load()
      if (onChanged) onChanged()
    } catch (e) {
      setActionError(e.message)
    } finally {
      setBusy(false)
    }
  }

  if (error) {
    return (
      <div role="alert" className="error">
        <p>Could not load the plan: {error}</p>
        <button type="button" onClick={load}>Retry</button>
      </div>
    )
  }
  if (!plan) return <p role="status">Loading plan…</p>

  const groups = GROUPS.map((g) => [g, plan.tests.filter((t) => t.status === g)]).filter(([, t]) => t.length)
  const draft = plan.status === 'draft'
  const pending = plan.status === 'pending_approval' && plan.approval && plan.approval.decision === 'pending'
  const canDecide = pending && plan.viewer_can_approve === true // server-computed hint
  const isRequester = pending && user && plan.approval.requested_by === user.id

  return (
    <section aria-labelledby="plan-title" className="plan">
      <h2 id="plan-title">Plan v{plan.version}: {planStatusLabel(plan.status)}</h2>
      <p className="notice" role="note">{plan.notice}</p>
      <p>
        Mode: {plan.mode.replace('_', ' ')} · Highest risk: <span className={`badge risk-${plan.risk_level}`}>{plan.risk_level}</span>
        {' '}· {plan.tests.length} check(s)
        {Object.entries(plan.counts).map(([k, v]) => ` · ${v} ${statusLabel(k).toLowerCase()}`)}
      </p>
      {plan.summary && <p>{plan.summary}</p>}
      {plan.prompt && <p>Prompt (stored as data): <q>{plan.prompt}</q></p>}
      {plan.content_sha256 && <p className="mono">Reviewed content hash: {plan.content_sha256}</p>}

      {plan.tests.length === 0 && <p>This plan contains no checks.</p>}
      {groups.map(([status, tests]) => (
        <div key={status} role="group" aria-label={statusLabel(status)}>
          <h3>{statusLabel(status)} ({tests.length})</h3>
          <p className="muted">{TEST_STATUS[status] ? TEST_STATUS[status].note : ''}</p>
          <ul className="tests">
            {tests.map((t) => (
              <TestRow
                key={t.id}
                test={t}
                editable={draft}
                busy={busy}
                onRemove={(id) => act(() => api.updatePlan(plan.id, { remove_test_ids: [id] }))}
              />
            ))}
          </ul>
        </div>
      ))}

      {actionError && <p role="alert" className="error">{actionError}</p>}

      {draft && (
        <button type="button" disabled={busy} onClick={() => act(() => api.submitPlan(plan.id))}>
          {busy ? 'Working…' : 'Submit for approval'}
        </button>
      )}

      {pending && (
        <form onSubmit={(e) => e.preventDefault()} aria-label="Decision" className="stack">
          <p>
            Approval requested at <strong>{plan.approval.risk_level}</strong> risk.
            {isRequester && ' You submitted this plan, so you cannot approve it; you can withdraw it.'}
            {!canDecide && !isRequester && ' Waiting for the project\'s designated approvers.'}
          </p>
          {(canDecide || isRequester) && (
            <>
              <label>
                Reason {plan.approval.risk_level === 'high' || plan.approval.risk_level === 'critical' ? '(required to approve high risk; at least 10 characters)' : '(required to reject)'}
                <textarea value={reason} onChange={(e) => setReason(e.target.value)} maxLength={2000} rows={3} />
              </label>
              {canDecide && !isRequester && (
                <button type="button" disabled={busy} onClick={() => decide('approved')}>Approve</button>
              )}
              <button type="button" disabled={busy} onClick={() => decide('rejected')}>
                {isRequester ? 'Withdraw' : 'Reject'}
              </button>
            </>
          )}
        </form>
      )}

      {plan.approval && plan.approval.decision !== 'pending' && (
        <p>
          Decision: <strong>{plan.approval.decision}</strong>
          {plan.approval.reason ? ` — ${plan.approval.reason}` : ''}
        </p>
      )}
    </section>
  )
}
