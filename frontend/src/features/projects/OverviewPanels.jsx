import { useCallback } from 'react'
import { Link } from 'react-router-dom'
import Card, { ProgressBar } from '../../components/Card.jsx'
import StatusBadge from '../../components/StatusBadge.jsx'
import { DataState, EmptyState } from '../../components/states.jsx'
import { useApi } from '../../hooks/useApi.js'
import { useLoad } from '../../hooks/useLoad.js'
import { formatDateTime } from '../../lib/format.js'
import { RESULT_STATUS } from '../runs/labels.js'
import './OverviewPanels.css'

// Each panel loads from the real API on its own, so one failing call does not blank the page,
// and a panel with nothing to show says "none yet" rather than showing a made-up value.
const newest = (items) => [...items].sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)))
const count = (items, pick) => items.reduce((acc, i) => ({ ...acc, [pick(i)]: (acc[pick(i)] || 0) + 1 }), {})

function Panel({ title, state, reload, empty, children, footer }) {
  return (
    <Card title={title} className="overview-card">
      <DataState state={state} onRetry={reload} empty={empty} what={title.toLowerCase()}>
        {children}
      </DataState>
      {footer && <p className="overview-link">{footer}</p>}
    </Card>
  )
}

export function AnalysisPanel({ projectId }) {
  const api = useApi()
  const [state, reload] = useLoad(useCallback(() => api.listAnalyses(projectId), [api, projectId]))
  return (
    <Panel title="Latest analysis" state={state} reload={reload} empty={<EmptyState title="No analysis yet">Upload a ZIP source and run an analysis.</EmptyState>} footer={<Link to={`/projects/${projectId}/analysis`}>Open analysis</Link>}>
      {(items) => {
        const a = newest(items)[0]
        const facts = (a.result && a.result.facts) || {}
        return (
          <>
            <p><StatusBadge domain="analysis" value={a.status} /> <span className="muted">{formatDateTime(a.created_at)}</span></p>
            <p className="muted">
              {facts.languages && facts.languages.length ? `Languages: ${facts.languages.map((l) => l.name).join(', ')}. ` : ''}
              {facts.test_files ? `${facts.test_files.count} test file(s) detected.` : ''}
            </p>
          </>
        )
      }}
    </Panel>
  )
}

export function PlansPanel({ projectId }) {
  const api = useApi()
  const [state, reload] = useLoad(useCallback(() => api.listPlans(projectId), [api, projectId]))
  return (
    <Panel title="Test plans" state={state} reload={reload} empty={<EmptyState title="No plans yet">Generate a recommended plan to see which checks apply.</EmptyState>} footer={<Link to={`/projects/${projectId}/plans`}>Open plans</Link>}>
      {(items) => {
        const p = newest(items)[0]
        return (
          <>
            <p>{items.length} plan(s). Latest: version {p.version} <StatusBadge domain="plan" value={p.status} /> <StatusBadge domain="risk" value={p.risk_level} /></p>
          </>
        )
      }}
    </Panel>
  )
}

export function RunPanel({ projectId }) {
  const api = useApi()
  const [state, reload] = useLoad(useCallback(() => api.listRuns(projectId), [api, projectId]))
  return (
    <Panel title="Latest run" state={state} reload={reload} empty={<EmptyState title="No runs yet">Approve a plan, then start a run from the Runs tab. Nothing has been executed.</EmptyState>} footer={<Link to={`/projects/${projectId}/runs`}>Open runs</Link>}>
      {(items) => {
        const run = newest(items)[0]
        const progress = run.progress
        const byStatus = (progress && progress.results_by_status) || {}
        return (
          <>
            <p><StatusBadge domain="run" value={run.status} /> <span className="muted">{formatDateTime(run.started_at || run.created_at)}</span></p>
            {progress && (
              <>
                <ProgressBar value={progress.tests_finished} max={Math.max(progress.tests_total, 1)} label="Checks finished" />
                <p className="muted">{progress.tests_finished} of {progress.tests_total} check(s) finished.</p>
              </>
            )}
            {Object.keys(byStatus).length > 0 && (
              <ul className="overview-counts">
                {Object.entries(byStatus).map(([status, n]) => (
                  <li key={status}><StatusBadge domain="result" value={status} /> <span aria-label={`${n} ${RESULT_STATUS[status] ? RESULT_STATUS[status].label : status}`}>{n}</span></li>
                ))}
              </ul>
            )}
          </>
        )
      }}
    </Panel>
  )
}

export function FindingsPanel({ projectId }) {
  const api = useApi()
  const [state, reload] = useLoad(useCallback(() => api.listFindings(projectId), [api, projectId]))
  return (
    <Panel title="Security findings" state={state} reload={reload} empty={<EmptyState title="No findings recorded">No security scan results are stored for this project. That does not mean it was scanned and found clean.</EmptyState>} footer={<Link to={`/projects/${projectId}/findings`}>Open findings</Link>}>
      {(items) => {
        const bySeverity = count(items, (f) => f.severity)
        const unverified = items.filter((f) => f.verification_state === 'unverified').length
        return (
          <>
            <p>{items.length} finding(s), {unverified} not yet verified by a person.</p>
            <ul className="overview-counts">
              {['critical', 'high', 'medium', 'low', 'info'].filter((s) => bySeverity[s]).map((s) => (
                <li key={s}><StatusBadge domain="severity" value={s} /> {bySeverity[s]}</li>
              ))}
            </ul>
          </>
        )
      }}
    </Panel>
  )
}

export function ApprovalsPanel({ projectId }) {
  const api = useApi()
  const [state, reload] = useLoad(useCallback(() => api.listApprovals('pending'), [api]))
  return (
    <Panel title="Approvals waiting for you" state={state} reload={reload} empty={<EmptyState title="Nothing is waiting for your decision" />} footer={<Link to="/approvals">Open approvals</Link>}>
      {(items) => {
        const here = items.filter((a) => a.project_id === projectId)
        return <p>{here.length === 0 ? 'None for this project.' : `${here.length} for this project, ${items.length} in total.`}</p>
      }}
    </Panel>
  )
}
