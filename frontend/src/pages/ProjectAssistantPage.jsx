import { useCallback } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import Alert from '../components/Alert.jsx'
import Card from '../components/Card.jsx'
import { DataState } from '../components/states.jsx'
import AgentRunTable from '../features/assistant/AgentRunTable.jsx'
import { canRun } from '../features/assistant/labels.js'
import PlannerForm from '../features/assistant/PlannerForm.jsx'
import { useApi } from '../hooks/useApi.js'
import { useLoad } from '../hooks/useLoad.js'

// The project's assistant: ask for a draft test plan, and see every assistant run with its
// outcome. Runs for findings are started from the finding.
export default function ProjectAssistantPage() {
  const { project } = useOutletContext()
  const api = useApi()
  const navigate = useNavigate()
  const [runs, reload] = useLoad(useCallback(() => api.listAgentRuns(project.id), [api, project.id]))
  return (
    <>
      <Alert tone="info" title="Suggestions, not decisions">
        The assistant uses built-in rules first and a model only when they are not enough. Everything it drafts still goes through your review and the normal approval steps, and none of it runs by itself.
      </Alert>
      <Card title="Draft a test plan">
        {canRun(project) && project.status === 'active' ? (
          <PlannerForm projectId={project.id} api={api} onCreated={(run) => navigate(`/projects/${project.id}/assistant/${run.id}`)} />
        ) : (
          <p className="muted">You need run access on an active project to ask the assistant for a plan.</p>
        )}
      </Card>
      <Card title="Assistant runs">
        <DataState state={runs} onRetry={reload} what="the assistant runs" loadingLabel="Loading assistant runs…" isEmpty={() => false}>
          {(items) => <AgentRunTable runs={items} projectId={project.id} />}
        </DataState>
      </Card>
    </>
  )
}
