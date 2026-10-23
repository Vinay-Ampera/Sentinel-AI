import { useCallback, useState } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import Alert from '../components/Alert.jsx'
import Button from '../components/Button.jsx'
import Card from '../components/Card.jsx'
import { DataState, EmptyState } from '../components/states.jsx'
import PlanList from '../features/plans/PlanList.jsx'
import { useApi } from '../hooks/useApi.js'
import { useLoad } from '../hooks/useLoad.js'
import { describeError } from '../lib/errors.js'

export default function ProjectPlansPage() {
  const { project } = useOutletContext()
  const api = useApi()
  const navigate = useNavigate()
  const pid = project.id
  const [plans, reload] = useLoad(useCallback(() => api.listPlans(pid), [api, pid]))
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState(null)

  async function generate() {
    setCreating(true)
    setError(null)
    try {
      const plan = await api.createPlan(pid, { mode: 'automatic' })
      navigate(`/projects/${pid}/plans/${plan.id}`)
    } catch (e) {
      setError(describeError(e).message)
      setCreating(false)
    }
  }

  return (
    <Card
      title="Test plans"
      actions={
        <Button variant="primary" onClick={generate} loading={creating} loadingLabel="Generating…" disabled={project.status === 'archived'} disabledReason="Archived projects cannot get new plans">
          Generate recommended plan
        </Button>
      }
    >
      <p className="muted">A plan lists the checks that apply, with their risk and why. Reviewing or approving a plan does not run anything; runs are started from the Runs tab.</p>
      {error && <Alert tone="danger" title="Could not generate a plan">{error}</Alert>}
      <DataState state={plans} onRetry={reload} what="this project's plans" loadingLabel="Loading plans…" empty={<EmptyState title="No plans yet">Generate a recommended plan to see which checks apply to this project.</EmptyState>}>
        {(items) => <PlanList plans={items} projectId={pid} />}
      </DataState>
    </Card>
  )
}
