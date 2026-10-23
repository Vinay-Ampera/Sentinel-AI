import { useCallback, useRef, useState } from 'react'
import { Link, useOutletContext, useParams } from 'react-router-dom'
import Alert from '../components/Alert.jsx'
import Button from '../components/Button.jsx'
import Card from '../components/Card.jsx'
import { ConfirmDialog } from '../components/Dialog.jsx'
import SectionHeader from '../components/SectionHeader.jsx'
import { DataState } from '../components/states.jsx'
import BatchTable from '../features/runs/BatchTable.jsx'
import { ACTIVE_RUN, CANCELLABLE_RUN } from '../features/runs/labels.js'
import ResultTable from '../features/runs/ResultTable.jsx'
import RunEvents from '../features/runs/RunEvents.jsx'
import RunSummary from '../features/runs/RunSummary.jsx'
import { useApi } from '../hooks/useApi.js'
import { usePolledLoad } from '../hooks/usePolledLoad.js'
import { useToast } from '../hooks/useToast.js'
import { describeError } from '../lib/errors.js'
import { formatDateTime, formatTime } from '../lib/format.js'

// Checks the run should have covered: plan items that were runnable, whatever has happened since.
const RUNNABLE = new Set(['approved', 'executed', 'failed_to_start'])

// The test execution report for one run: verdict, facts, outcomes, every check with its result,
// batches and the event trail. It refreshes by itself while the run is active, and a failed
// refresh keeps the last good data visible.
export default function RunReportPage() {
  const { project } = useOutletContext()
  const { runId } = useParams()
  const api = useApi()
  const { notify } = useToast()
  const [cancelling, setCancelling] = useState(false)
  const planCache = useRef(null)

  const load = useCallback(async () => {
    const run = await api.getRun(runId)
    if (!planCache.current || planCache.current.id !== run.plan_id) {
      planCache.current = await api.getPlan(run.plan_id).catch(() => null) // names are a nicety; the report works without
    }
    const [results, batches, events] = await Promise.all([api.listRunResults(runId), api.listRunBatches(runId), api.listRunEvents(runId, 0)])
    return { run, results, batches, events, plan: planCache.current }
  }, [api, runId])
  const [state, reload] = usePolledLoad(load, (d) => (d ? ACTIVE_RUN.has(d.run.status) : false))

  async function cancel() {
    try {
      await api.cancelRun(runId)
      notify({ tone: 'success', title: 'Cancel requested' })
    } catch (e) {
      notify({ tone: 'danger', title: 'Could not cancel the run', message: describeError(e).message })
    }
    reload()
  }

  return (
    <>
      <p><Link to={`/projects/${project.id}/runs`}>Back to all runs</Link></p>
      <DataState state={state.data ? { ...state, error: null } : state} onRetry={reload} what="this run" loadingLabel="Loading the run report…" isEmpty={() => false}>
        {({ run, results, batches, events, plan }) => {
          const tests = plan ? plan.tests : []
          const byTest = new Map(results.map((r) => [r.planned_test_id, r]))
          const known = new Map(tests.map((t) => [t.id, t]))
          const rows = [
            ...results.map((r) => ({ key: r.id, name: known.get(r.planned_test_id) ? known.get(r.planned_test_id).name : 'Check (name not available)', tool: known.get(r.planned_test_id)?.tool, result: r })),
            ...tests.filter((t) => RUNNABLE.has(t.status) && !byTest.has(t.id)).map((t) => ({ key: `none-${t.id}`, name: t.name, tool: t.tool, result: null })),
          ]
          return (
            <>
              <SectionHeader title="Test execution report">
                <p className="muted">
                  {plan ? <>Plan <Link to={`/projects/${project.id}/plans/${run.plan_id}`}>version {plan.version}</Link> · </> : null}
                  created {formatDateTime(run.created_at)}
                  {CANCELLABLE_RUN.has(run.status) && <> · <Button size="sm" variant="danger" onClick={() => setCancelling(true)}>Cancel run</Button></>}
                </p>
              </SectionHeader>
              {state.error && <Alert tone="warning" title="Could not refresh">Showing the last update, {formatTime(state.updatedAt)}.</Alert>}
              {!plan && <Alert tone="neutral">The plan for this run could not be read, so check names and checks without a result are not shown.</Alert>}
              <RunSummary run={run} results={results} updatedAt={state.updatedAt} />
              <Card title="Checks">
                <ResultTable rows={rows} projectId={project.id} runId={runId} runActive={ACTIVE_RUN.has(run.status)} />
              </Card>
              <Card title="Batches">
                <p className="muted">The run is split into batches of checks. Retries and start-up problems show here.</p>
                <BatchTable batches={batches} />
              </Card>
              <Card title="Event trail">
                <RunEvents events={events} />
              </Card>
              <ConfirmDialog open={cancelling} onClose={() => setCancelling(false)} title="Cancel this run?" confirmLabel="Cancel run" danger onConfirm={async () => { await cancel(); setCancelling(false) }}>
                <p>Checks that have not started will not run. A check already running is asked to stop.</p>
              </ConfirmDialog>
            </>
          )
        }}
      </DataState>
    </>
  )
}
