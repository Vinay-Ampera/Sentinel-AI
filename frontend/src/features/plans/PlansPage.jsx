import { useCallback, useEffect, useState } from 'react'
import PlanReview from './PlanReview.jsx'
import RunsPanel from '../runs/RunsPanel.jsx'
import { planStatusLabel } from './labels.js'
import './plans.css'

// Fetch when `fn` (a memoized loader) changes or reload() is called. `loading` is derived
// from which request the stored result belongs to, so no state is set synchronously.
function useLoad(fn) {
  const [tick, setTick] = useState(0)
  const [result, setResult] = useState({ key: null, error: null, data: null })
  const key = `${tick}`
  useEffect(() => {
    let live = true
    fn()
      .then((data) => live && setResult({ key: fn, tick, error: null, data }))
      .catch((e) => live && setResult({ key: fn, tick, error: e.message, data: null }))
    return () => {
      live = false
    }
  }, [fn, tick])
  const current = result.key === fn && result.tick === tick
  const state = current
    ? { loading: false, error: result.error, data: result.data }
    : { loading: true, error: null, data: null }
  return [state, () => setTick((t) => t + 1), key]
}

export default function PlansPage({ api, user }) {
  const [projectId, setProjectId] = useState('')
  const [planId, setPlanId] = useState(null)
  const [createError, setCreateError] = useState(null)
  const [creating, setCreating] = useState(false)

  const loadProjects = useCallback(() => api.listProjects(), [api])
  const loadPlans = useCallback(
    () => (projectId ? api.listPlans(projectId) : Promise.resolve([])),
    [api, projectId],
  )
  const loadInbox = useCallback(() => api.listApprovals('pending'), [api])
  const [projects] = useLoad(loadProjects)
  const [plans, reloadPlans] = useLoad(loadPlans)
  const [inbox, reloadInbox] = useLoad(loadInbox)

  async function create() {
    setCreating(true)
    setCreateError(null)
    try {
      const plan = await api.createPlan(projectId, { mode: 'automatic' })
      setPlanId(plan.id)
      reloadPlans()
    } catch (e) {
      setCreateError(e.message)
    } finally {
      setCreating(false)
    }
  }

  const refresh = () => {
    reloadPlans()
    reloadInbox()
  }

  return (
    <div className="plan">
      <section aria-labelledby="inbox-title">
        <h2 id="inbox-title">Approvals waiting for you</h2>
        {inbox.loading && <p role="status">Loading approvals…</p>}
        {inbox.error && <p role="alert" className="error">{inbox.error}</p>}
        {inbox.data && inbox.data.length === 0 && <p>Nothing is waiting for your decision.</p>}
        {inbox.data && inbox.data.length > 0 && (
          <ul>
            {inbox.data.map((a) => (
              <li key={a.id}>
                {a.kind === 'plan' ? (
                  <button type="button" onClick={() => setPlanId(a.plan_id)}>
                    Review plan ({a.risk_level} risk)
                  </button>
                ) : (
                  <span>Target authorization ({a.risk_level} risk) — decide via the approvals API</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="plans-title">
        <h2 id="plans-title">Test plans</h2>
        {projects.loading && <p role="status">Loading projects…</p>}
        {projects.error && <p role="alert" className="error">{projects.error}</p>}
        {projects.data && projects.data.length === 0 && <p>You have no projects yet.</p>}
        {projects.data && projects.data.length > 0 && (
          <label>
            Project{' '}
            <select value={projectId} onChange={(e) => { setProjectId(e.target.value); setPlanId(null) }}>
              <option value="">Select a project…</option>
              {projects.data.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </label>
        )}
        {projectId && (
          <>
            <button type="button" onClick={create} disabled={creating}>
              {creating ? 'Generating…' : 'Generate recommended plan'}
            </button>
            {createError && <p role="alert" className="error">{createError}</p>}
            {plans.loading && <p role="status">Loading plans…</p>}
            {plans.error && <p role="alert" className="error">{plans.error}</p>}
            {plans.data && plans.data.length === 0 && <p>No plans yet for this project.</p>}
            {plans.data && plans.data.length > 0 && (
              <ul>
                {plans.data.map((p) => (
                  <li key={p.id}>
                    <button type="button" onClick={() => setPlanId(p.id)} aria-current={p.id === planId}>
                      v{p.version} · {planStatusLabel(p.status)} · risk {p.risk_level}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </section>

      {projectId && <RunsPanel key={projectId} api={api} projectId={projectId} plans={plans.data} />}

      {planId && <PlanReview key={planId} api={api} planId={planId} user={user} onChanged={refresh} />}
    </div>
  )
}
