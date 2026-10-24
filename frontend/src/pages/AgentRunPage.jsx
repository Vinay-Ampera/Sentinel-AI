import { useCallback } from 'react'
import { Link, useOutletContext, useParams } from 'react-router-dom'
import SectionHeader from '../components/SectionHeader.jsx'
import { DataState } from '../components/states.jsx'
import AgentRunDetail from '../features/assistant/AgentRunDetail.jsx'
import { useApi } from '../hooks/useApi.js'
import { useLoad } from '../hooks/useLoad.js'

export default function AgentRunPage() {
  const { project } = useOutletContext()
  const { runId } = useParams()
  const api = useApi()
  const [run, reload] = useLoad(useCallback(() => api.getAgentRun(project.id, runId), [api, project.id, runId]))
  return (
    <>
      <p><Link to={`/projects/${project.id}/assistant`}>Back to the assistant</Link></p>
      <DataState state={run} onRetry={reload} what="this assistant run" loadingLabel="Loading assistant run…" isEmpty={() => false}>
        {(data) => (
          <>
            <SectionHeader title="Assistant run" />
            <AgentRunDetail run={data} projectId={project.id} />
          </>
        )}
      </DataState>
    </>
  )
}
