import { useCallback, useEffect, useRef, useState } from 'react'
import { ACTIVE_RUN, CANCELLABLE_RUN, caseLabel, resultLabel, resultNote, runLabel } from './labels.js'
import './runs.css'

// Load once, reload on demand, and keep reloading while `active` (a boolean, or a function of
// the loaded data) is true.
function usePolled(load, active, pollMs) {
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
  const polling = typeof active === 'function' ? active(state.data) : active
  useEffect(() => {
    if (!polling) return undefined
    const id = setInterval(() => setTick((t) => t + 1), pollMs)
    return () => clearInterval(id)
  }, [polling, pollMs])
  return [state, () => setTick((t) => t + 1)]
}

function Evidence({ api, item }) {
  const [view, setView] = useState(null)
  const [error, setError] = useState(null)
  async function open() {
    setError(null)
    try {
      setView(await api.getEvidenceText(item.id))
    } catch (e) {
      setError(e.message)
    }
  }
  return (
    <li>
      {item.name} <span className="muted">({item.size_bytes} bytes)</span>{' '}
      <button type="button" onClick={open}>View {item.name}</button>
      {error && <span role="alert" className="error"> {error}</span>}
      {view && (
        <>
          <pre className="evidence-view" aria-label={`Contents of ${item.name}`}>{view.text}</pre>
          {view.truncated && <p className="muted">Shortened for display; download the file for the rest.</p>}
        </>
      )}
    </li>
  )
}

function ResultDetail({ api, runId, resultId }) {
  const load = useCallback(() => api.getRunResult(runId, resultId), [api, runId, resultId])
  const [detail] = usePolled(load, false, 0)
  if (detail.loading) return <p role="status">Loading result…</p>
  if (detail.error) return <p role="alert" className="error">{detail.error}</p>
  const d = detail.data
  return (
    <div>
      {d.cases.length === 0 && <p className="muted">This check reported no individual cases.</p>}
      {d.cases.length > 0 && (
        <table className="cases">
          <caption>Cases reported by the project&apos;s own test report</caption>
          <thead><tr><th>Name</th><th>Outcome</th><th>Message</th></tr></thead>
          <tbody>
            {d.cases.map((c) => (
              <tr key={c.ordinal}>
                <td>{c.classname ? `${c.classname}::` : ''}{c.name}</td>
                <td>{caseLabel(c.status)}</td>
                <td>{c.message || ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <h4>Evidence</h4>
      <p className="muted">Output from the sandbox is untrusted text; secrets are redacted before it is stored.</p>
      {d.evidence.length === 0 && <p>No evidence was stored for this check.</p>}
      <ul>{d.evidence.map((ev) => <Evidence key={ev.id} api={api} item={ev} />)}</ul>
    </div>
  )
}

function RunDetail({ api, run, pollMs }) {
  const [openResult, setOpenResult] = useState(null)
  // The run and its results are loaded together, and polling follows the *fresh* status.
  const loadBoth = useCallback(
    async () => {
      const [fresh, results] = await Promise.all([api.getRun(run.id), api.listRunResults(run.id)])
      return { fresh, results }
    },
    [api, run.id],
  )
  const isActive = (d) => ACTIVE_RUN.has(d ? d.fresh.status : run.status)
  const [both] = usePolled(loadBoth, isActive, pollMs)
  const loadPlan = useCallback(() => api.getPlan(run.plan_id), [api, run.plan_id])
  const [plan] = usePolled(loadPlan, false, 0)
  const names = new Map(((plan.data && plan.data.tests) || []).map((t) => [t.id, t.name]))
  const current = (both.data && both.data.fresh) || run
  const results = { loading: both.loading, error: both.error, data: both.data && both.data.results }
  const p = current.progress

  return (
    <section aria-labelledby="run-detail-title" className="run-detail">
      <h3 id="run-detail-title">Run details</h3>
      <p>
        {runLabel(current.status)}
        {p && ` · ${p.tests_finished} of ${p.tests_total} checks have a result`}
      </p>
      {current.error_summary && <p role="alert" className="error">{current.error_summary}</p>}
      {p && p.cases_by_status && Object.keys(p.cases_by_status).length > 0 && (
        <p className="muted">
          Cases: {Object.entries(p.cases_by_status).map(([k, v]) => `${v} ${caseLabel(k).toLowerCase()}`).join(', ')}
        </p>
      )}
      {results.loading && <p role="status">Loading results…</p>}
      {results.error && <p role="alert" className="error">{results.error}</p>}
      {results.data && results.data.length === 0 && <p>No results yet.</p>}
      {results.data && results.data.length > 0 && (
        <ul className="run-list">
          {results.data.map((r) => (
            <li key={r.id} className={`run result-${r.status}`}>
              <div className="run-head">
                <strong>{names.get(r.planned_test_id) || 'Check'}</strong>
                <span className="badge" title={resultNote(r.status)}>{resultLabel(r.status)}</span>
                <button type="button" onClick={() => setOpenResult(openResult === r.id ? null : r.id)}>
                  {openResult === r.id ? 'Hide details' : 'Show details'}
                </button>
              </div>
              {r.summary && <p className="reason">{r.summary}</p>}
              {openResult === r.id && <ResultDetail api={api} runId={run.id} resultId={r.id} />}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export default function RunsPanel({ api, projectId, plans, pollMs = 3000 }) {
  const [selected, setSelected] = useState(null)
  const [planId, setPlanId] = useState('')
  const [starting, setStarting] = useState(false)
  const [actionError, setActionError] = useState(null)
  const keyRef = useRef(null)

  const loadRuns = useCallback(() => api.listRuns(projectId), [api, projectId])
  const [runs, reload] = usePolled(loadRuns, (list) => !!list && list.some((r) => ACTIVE_RUN.has(r.status)), pollMs)

  const approved = (plans || []).filter((p) => p.status === 'approved')

  async function start() {
    setStarting(true)
    setActionError(null)
    // One key per attempt: a double click or a retry returns the original run.
    keyRef.current = keyRef.current || crypto.randomUUID()
    try {
      const run = await api.createRun(projectId, planId, keyRef.current)
      keyRef.current = null
      setSelected(run)
      reload()
    } catch (e) {
      setActionError(e.message)
    } finally {
      setStarting(false)
    }
  }

  async function cancel(run) {
    setActionError(null)
    try {
      await api.cancelRun(run.id)
      reload()
    } catch (e) {
      setActionError(e.message)
    }
  }

  return (
    <section aria-labelledby="runs-title" className="runs">
      <h2 id="runs-title">Test runs</h2>
      {approved.length === 0 && <p>No approved plan to run yet. Submit a plan and get it approved first.</p>}
      {approved.length > 0 && (
        <p>
          <label>
            Plan to run{' '}
            <select value={planId} onChange={(e) => setPlanId(e.target.value)}>
              <option value="">Select an approved plan…</option>
              {approved.map((p) => <option key={p.id} value={p.id}>v{p.version} · risk {p.risk_level}</option>)}
            </select>
          </label>{' '}
          <button type="button" onClick={start} disabled={!planId || starting}>
            {starting ? 'Starting…' : 'Start run'}
          </button>
        </p>
      )}
      {actionError && <p role="alert" className="error">{actionError}</p>}
      {runs.loading && <p role="status">Loading runs…</p>}
      {runs.error && <p role="alert" className="error">{runs.error}</p>}
      {runs.data && runs.data.length === 0 && <p>No runs yet for this project.</p>}
      {runs.data && runs.data.length > 0 && (
        <ul className="run-list" aria-label="Run history">
          {runs.data.map((r) => (
            <li key={r.id} className="run" aria-current={selected && selected.id === r.id}>
              <div className="run-head">
                <span className="badge">{runLabel(r.status)}</span>
                <span className="muted">{new Date(r.created_at).toLocaleString()}</span>
                <button type="button" onClick={() => setSelected(r)}>Details</button>
                {CANCELLABLE_RUN.has(r.status) && (
                  <button type="button" onClick={() => cancel(r)}>Cancel run</button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      {selected && <RunDetail key={selected.id} api={api} run={selected} pollMs={pollMs} />}
    </section>
  )
}
