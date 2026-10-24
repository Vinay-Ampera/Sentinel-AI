import { useCallback } from 'react'
import { Link, useOutletContext, useParams } from 'react-router-dom'
import SectionHeader from '../components/SectionHeader.jsx'
import { DataState } from '../components/states.jsx'
import TraceView from '../features/alerts/TraceView.jsx'
import { useApi } from '../hooks/useApi.js'
import { useLoad } from '../hooks/useLoad.js'

export default function TracePage() {
  const { project } = useOutletContext()
  const { traceId } = useParams()
  const api = useApi()
  const [loaded, reload] = useLoad(useCallback(() => api.getTrace(project.id, traceId), [api, project.id, traceId]))
  return (
    <>
      <p><Link to={`/projects/${project.id}/alerts`}>Back to alerts</Link></p>
      <SectionHeader title="Trace" />
      <p className="mono">{traceId}</p>
      <DataState state={loaded} onRetry={reload} what="this trace" loadingLabel="Loading trace…" isEmpty={() => false}>
        {(t) => <TraceView trace={t} projectId={project.id} />}
      </DataState>
    </>
  )
}
