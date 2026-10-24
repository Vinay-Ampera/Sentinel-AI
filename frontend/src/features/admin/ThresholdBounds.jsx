import { useCallback, useState } from 'react'
import Alert from '../../components/Alert.jsx'
import Button from '../../components/Button.jsx'
import Card from '../../components/Card.jsx'
import { DataState } from '../../components/states.jsx'
import { useApi } from '../../hooks/useApi.js'
import { useLoad } from '../../hooks/useLoad.js'
import { useToast } from '../../hooks/useToast.js'
import { describeError } from '../../lib/errors.js'
import './ThresholdBounds.css'

const label = (name) => name.replace(/_/g, ' ')

function Editor({ limits, saved, onSave }) {
  const start = (l) => ({ min: String(saved?.[l.name]?.min ?? l.min), max: String(saved?.[l.name]?.max ?? l.max) })
  const [values, setValues] = useState(() => Object.fromEntries(limits.map((l) => [l.name, start(l)])))
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const set = (name, side, v) => setValues((cur) => ({ ...cur, [name]: { ...cur[name], [side]: v } }))
  const problem = (l) => {
    const lo = Number(values[l.name].min)
    const hi = Number(values[l.name].max)
    if (values[l.name].min === '' || values[l.name].max === '' || Number.isNaN(lo) || Number.isNaN(hi)) return 'Enter both numbers.'
    if (lo > hi) return 'The minimum must not exceed the maximum.'
    if (lo < l.min || hi > l.max) return `Stay inside the built-in range ${l.min} to ${l.max}.`
    return ''
  }
  const problems = Object.fromEntries(limits.map((l) => [l.name, problem(l)]))
  const invalid = Object.values(problems).some(Boolean)

  async function submit(map) {
    setBusy(true)
    setError(null)
    try {
      await onSave(map)
    } catch (e) {
      setError(e.status === 403 || e.status === 422 ? e.message : describeError(e).message)
    } finally {
      setBusy(false)
    }
  }
  const save = () => submit(Object.fromEntries(limits.map((l) => [l.name, { min: Number(values[l.name].min), max: Number(values[l.name].max) }])))
  const reset = () => {
    setValues(Object.fromEntries(limits.map((l) => [l.name, { min: String(l.min), max: String(l.max) }])))
    return submit(Object.fromEntries(limits.map((l) => [l.name, { min: l.min, max: l.max }])))
  }

  return (
    <>
      {error && <Alert tone="danger" title="The limits were not saved">{error}</Alert>}
      <div className="table-scroll" role="region" aria-label="Alert threshold limits table" tabIndex={0}>
        <table className="data-table threshold-table">
          <caption className="visually-hidden">Alert threshold limits</caption>
          <thead>
            <tr>
              <th scope="col">Threshold</th>
              <th scope="col">Built-in range (default)</th>
              <th scope="col">Lowest a project may set</th>
              <th scope="col">Highest a project may set</th>
            </tr>
          </thead>
          <tbody>
            {limits.map((l) => (
              <tr key={l.name}>
                <th scope="row">
                  <span className="threshold-name">{label(l.name)}</span>
                  <span className="muted threshold-help">{l.description}</span>
                  {problems[l.name] && <span className="error threshold-help" role="alert">{problems[l.name]}</span>}
                </th>
                <td>{l.min} to {l.max} ({l.default})</td>
                <td><input type="number" aria-label={`Lowest ${label(l.name)}`} value={values[l.name].min} step="any" min={l.min} max={l.max} onChange={(e) => set(l.name, 'min', e.target.value)} aria-invalid={problems[l.name] ? true : undefined} /></td>
                <td><input type="number" aria-label={`Highest ${label(l.name)}`} value={values[l.name].max} step="any" min={l.min} max={l.max} onChange={(e) => set(l.name, 'max', e.target.value)} aria-invalid={problems[l.name] ? true : undefined} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="threshold-actions">
        <Button variant="primary" loading={busy} loadingLabel="Saving…" disabled={busy || invalid} onClick={save}>Save limits</Button>
        <Button disabled={busy} onClick={reset}>Reset to built-in limits</Button>
      </div>
    </>
  )
}

// Organization limits for the alert thresholds a project may set (super admin). An organization
// can only narrow a built-in range, never widen it; projects stay inside it, and a project value
// that falls outside later limits is clamped when read.
export default function ThresholdBounds() {
  const api = useApi()
  const { notify } = useToast()
  const [limits, reloadLimits] = useLoad(useCallback(() => api.getAlertThresholdLimits(), [api]))
  const [policies, reloadPolicies] = useLoad(useCallback(() => api.getGlobalPolicies(), [api]))
  const state = { loading: limits.loading || policies.loading, error: limits.error || policies.error, errorMessage: limits.errorMessage || policies.errorMessage, data: limits.data && policies.data ? { limits: limits.data, saved: policies.data.alert_threshold_bounds } : null }
  const save = async (map) => {
    await api.setGlobalPolicy('alert_threshold_bounds', map)
    notify({ tone: 'success', title: 'Alert threshold limits saved' })
    reloadPolicies()
  }
  return (
    <Card title="Alert threshold limits">
      <DataState state={state} onRetry={() => { reloadLimits(); reloadPolicies() }} what="alert threshold limits" loadingLabel="Loading limits…" isEmpty={() => false}>
        {(d) => (
          <>
            <Alert tone="info">These limits apply to every project's alert thresholds. You can only narrow a built-in range, never widen it. A project value outside a new limit is treated as the nearest limit. Only a super admin may change them.</Alert>
            <Editor key={JSON.stringify(d.saved || null)} limits={d.limits} saved={d.saved} onSave={save} />
          </>
        )}
      </DataState>
    </Card>
  )
}
