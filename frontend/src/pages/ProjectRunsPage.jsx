import { useCallback, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import Alert from '../components/Alert.jsx'
import Card from '../components/Card.jsx'
import Field from '../components/Field.jsx'
import Pagination from '../components/Pagination.jsx'
import { DataState, EmptyState } from '../components/states.jsx'
import { ACTIVE_RUN, RUN_STATUS } from '../features/runs/labels.js'
import RunTable from '../features/runs/RunTable.jsx'
import StartRunCard from '../features/runs/StartRunCard.jsx'
import { useApi } from '../hooks/useApi.js'
import { useLoad } from '../hooks/useLoad.js'
import { usePagination } from '../hooks/usePagination.js'
import { usePolledLoad } from '../hooks/usePolledLoad.js'
import { useToast } from '../hooks/useToast.js'
import { describeError } from '../lib/errors.js'
import './ProjectRunsPage.css'

// Start runs and see run history. The list refreshes by itself while any run is active.
export default function ProjectRunsPage() {
  const { project } = useOutletContext()
  const api = useApi()
  const { notify } = useToast()
  const pid = project.id
  const [status, setStatus] = useState('')
  const [plans, reloadPlans] = useLoad(useCallback(() => api.listPlans(pid), [api, pid]))
  const [runs, reloadRuns] = usePolledLoad(useCallback(() => api.listRuns(pid), [api, pid]), (list) => Boolean(list) && list.some((r) => ACTIVE_RUN.has(r.status)))
  const planVersions = Object.fromEntries((plans.data || []).map((p) => [p.id, p.version]))
  const sorted = [...(runs.data || [])].sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)))
  const shown = status ? sorted.filter((r) => r.status === status) : sorted
  const paging = usePagination(shown, 20)

  async function cancel(run) {
    try {
      await api.cancelRun(run.id)
      notify({ tone: 'success', title: 'Cancel requested', message: 'Checks that have not started will not run.' })
    } catch (e) {
      notify({ tone: 'danger', title: 'Could not cancel the run', message: describeError(e).message })
    }
    reloadRuns()
  }

  return (
    <>
      <DataState state={plans} onRetry={reloadPlans} what="this project's plans" loadingLabel="Loading plans…" isEmpty={() => false}>
        {(items) => <StartRunCard api={api} projectId={pid} plans={items} archived={project.status === 'archived'} />}
      </DataState>

      <Card title="Run history">
        <Field as="select" label="Status" value={status} onChange={(e) => setStatus(e.target.value)} className="runs-filter">
          <option value="">All runs</option>
          {Object.entries(RUN_STATUS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </Field>
        {runs.error && runs.data && <Alert tone="warning">Could not refresh the list. Showing the last update.</Alert>}
        <DataState
          state={runs.data ? { ...runs, error: null } : runs}
          onRetry={reloadRuns}
          what="this project's runs"
          loadingLabel="Loading runs…"
          empty={<EmptyState title="No runs yet">Approve a plan, then start a run above. Nothing has been executed for this project.</EmptyState>}
        >
          {() => (
            <>
              <RunTable runs={paging.pageItems} projectId={pid} planVersions={planVersions} onCancel={cancel} />
              <Pagination page={paging.page} pageCount={paging.pageCount} onPageChange={paging.setPage} label="Run pages" />
            </>
          )}
        </DataState>
      </Card>
    </>
  )
}
