import { useCallback, useEffect, useState } from 'react'
import {
  MANUAL_VERIFICATION,
  NEXT_STATUS,
  NOTE_STATUSES,
  confidenceLabel,
  severityLabel,
  statusLabel,
  verificationLabel,
  verificationNote,
} from './labels.js'
import '../runs/runs.css'

function useLoaded(load) {
  const [state, setState] = useState({ loading: true, error: null, data: null })
  const [tick, setTick] = useState(0)
  useEffect(() => {
    let live = true
    load()
      .then((data) => live && setState({ loading: false, error: null, data }))
      .catch((e) => live && setState((s) => ({ loading: false, error: e.message, data: s.data })))
    return () => {
      live = false
    }
  }, [load, tick])
  return [state, () => setTick((t) => t + 1)]
}

function EvidenceLink({ api, item }) {
  const [view, setView] = useState(null)
  const [error, setError] = useState(null)
  async function open() {
    setError(null)
    try {
      setView(await api.getEvidenceText(item.artifact_id))
    } catch (e) {
      setError(e.message)
    }
  }
  return (
    <li>
      {item.filename || 'evidence'} <span className="muted">({item.size_bytes} bytes)</span>{' '}
      <button type="button" onClick={open}>View {item.filename || 'evidence'}</button>
      {error && <span role="alert" className="error"> {error}</span>}
      {view && <pre className="evidence-view" aria-label={`Contents of ${item.filename}`}>{view.text}</pre>}
    </li>
  )
}

function FindingDetail({ api, id, onChanged }) {
  const load = useCallback(() => api.getFinding(id), [api, id])
  const [loaded, reload] = useLoaded(load)
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
      await fn()
      setStatus('')
      setStatusNote('')
      setState('')
      setStateNote('')
      reload()
      onChanged()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  if (loaded.loading) return <p role="status">Loading finding…</p>
  if (loaded.error && !loaded.data) return <p role="alert" className="error">{loaded.error}</p>
  const f = loaded.data
  const options = NEXT_STATUS[f.status] || []
  return (
    <div className="finding-detail">
      <p>
        {f.description}
        {f.file_path && <span className="muted"> — {f.file_path}{f.line_number ? `:${f.line_number}` : ''}</span>}
      </p>
      <p className="muted">
        Reported by {f.detected_by}
        {f.rule_id ? ` (${f.rule_id})` : ''}; seen in {f.occurrences} scan{f.occurrences === 1 ? '' : 's'}.
        {f.component ? ` Component: ${f.component}.` : ''}
        {f.cwe ? ` CWE-${f.cwe}.` : ''}
        {f.aliases && f.aliases.length > 1 ? ` Also known as ${f.aliases.slice(1).join(', ')}.` : ''}
      </p>
      {f.related && f.related.length > 0 && (
        <>
          <h4>Also reported by other scanners</h4>
          <p className="muted">
            These findings probably describe the same issue. They are linked, not merged: each keeps its own
            tool, evidence and status.
          </p>
          <ul aria-label="Related findings">
            {f.related.map((r) => (
              <li key={r.id}>
                {r.detected_by}: {r.title} — {statusLabel(r.status)}
                {r.file_path ? ` (${r.file_path}${r.line_number ? `:${r.line_number}` : ''})` : ''}
              </li>
            ))}
          </ul>
        </>
      )}
      {f.limitations && <p className="reason"><strong>Limitations:</strong> {f.limitations}</p>}

      <h4>Evidence</h4>
      {f.evidence.length === 0 && <p>No evidence is linked to this finding, so it cannot be confirmed.</p>}
      <ul>{f.evidence.map((ev) => <EvidenceLink key={ev.artifact_id} api={api} item={ev} />)}</ul>

      <h4>Verification attempts</h4>
      {f.attempts.length === 0 && <p>None yet.</p>}
      <ul>
        {f.attempts.map((a) => (
          <li key={a.id}>
            {a.method === 'rescan' ? 'Automatic re-scan' : 'Manual'}: {a.outcome.replace('_', ' ')}
            {a.notes ? ` — ${a.notes}` : ''}
          </li>
        ))}
      </ul>

      <h4>History</h4>
      <ol>
        {f.events.map((e) => (
          <li key={e.id}>
            {e.event_type.replace('_', ' ')}
            {e.to_value ? `: ${e.from_value ? `${e.from_value} → ` : ''}${e.to_value}` : ''}
            {e.detail && e.detail.note ? ` — ${e.detail.note}` : ''}
          </li>
        ))}
      </ol>

      <h4>Review</h4>
      {error && <p role="alert" className="error">{error}</p>}
      <div className="row">
        <label>
          Change status
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">Choose…</option>
            {options.map((s) => <option key={s} value={s}>{statusLabel(s)}</option>)}
          </select>
        </label>
        {NOTE_STATUSES.has(status) && (
          <label>
            Reason (required; administrators only)
            <input value={statusNote} onChange={(e) => setStatusNote(e.target.value)} />
          </label>
        )}
        <button type="button" disabled={!status || busy} onClick={() => act(() => api.setFindingStatus(id, status, statusNote))}>
          Apply status
        </button>
      </div>
      <div className="row">
        <label>
          My verification judgement
          <select value={state} onChange={(e) => setState(e.target.value)}>
            <option value="">Choose…</option>
            {MANUAL_VERIFICATION.map((s) => <option key={s} value={s}>{verificationLabel(s)}</option>)}
          </select>
        </label>
        <label>
          Note (at least 10 characters)
          <input value={stateNote} onChange={(e) => setStateNote(e.target.value)} />
        </label>
        <button
          type="button"
          disabled={!state || stateNote.trim().length < 10 || busy}
          onClick={() => act(() => api.setFindingVerification(id, state, stateNote))}
        >
          Record judgement
        </button>
      </div>
    </div>
  )
}

export default function FindingsPanel({ api, projectId }) {
  const [filter, setFilter] = useState('')
  const [openId, setOpenId] = useState(null)
  const load = useCallback(() => api.listFindings(projectId, { status: filter }), [api, projectId, filter])
  const [findings, reload] = useLoaded(load)
  return (
    <section aria-labelledby="findings-title" className="runs">
      <h2 id="findings-title">Security findings</h2>
      <p className="muted">
        Findings come from scanners (Bandit, Semgrep, the dependency audit and, where enabled, OWASP ZAP). Each
        one is a lead until a reviewer checks it: a scanner never marks a finding confirmed, and a clean scan
        does not mean the code is secure. Findings that several scanners report for the same issue are linked.
      </p>
      <label>
        Show
        <select value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">All findings</option>
          <option value="new">New</option>
          <option value="triaged">Triaged</option>
          <option value="reopened">Reopened</option>
          <option value="fixed">Fixed</option>
          <option value="verified_fixed">Fixed (re-scan verified)</option>
          <option value="false_positive">False positives</option>
          <option value="accepted_risk">Accepted risk</option>
        </select>
      </label>
      {findings.loading && <p role="status">Loading findings…</p>}
      {findings.error && <p role="alert" className="error">{findings.error}</p>}
      {findings.data && findings.data.length === 0 && <p>No findings. Run a security scan from an approved plan to look for some.</p>}
      {findings.data && findings.data.length > 0 && (
        <ul className="run-list" aria-label="Findings">
          {findings.data.map((f) => (
            <li key={f.id} className={`run severity-${f.severity}`}>
              <div className="run-head">
                <strong>{f.title}</strong>
                <span className="badge">{severityLabel(f.severity)} severity</span>
                <span className="badge">{confidenceLabel(f.confidence)} confidence</span>
                {f.detected_by && <span className="badge">{f.detected_by}</span>}
                {f.group_id && <span className="badge" title="Also reported by another scanner or advisory">Linked duplicate</span>}
                <span className="badge" title={verificationNote(f.verification_state)}>{verificationLabel(f.verification_state)}</span>
                <span className="badge">{statusLabel(f.status)}</span>
                <button type="button" onClick={() => setOpenId(openId === f.id ? null : f.id)}>
                  {openId === f.id ? 'Hide details' : 'Show details'}
                </button>
              </div>
              {(f.component || f.file_path) && (
                <p className="muted">
                  {f.component || ''}{f.component && f.file_path ? ' — ' : ''}
                  {f.file_path || ''}{f.file_path && f.line_number ? `:${f.line_number}` : ''}
                </p>
              )}
              {openId === f.id && <FindingDetail api={api} id={f.id} onChanged={reload} />}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
