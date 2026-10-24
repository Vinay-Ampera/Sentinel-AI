import { useCallback, useState } from 'react'
import { Link, useOutletContext, useParams } from 'react-router-dom'
import PageHeaderLite from '../components/SectionHeader.jsx'
import { DataState } from '../components/states.jsx'
import FindingAssist from '../features/assistant/FindingAssist.jsx'
import { canRun } from '../features/assistant/labels.js'
import FindingDetailView from '../features/findings/FindingDetailView.jsx'
import { useApi } from '../hooks/useApi.js'
import { useLoad } from '../hooks/useLoad.js'

// One finding inside its project. After a review action the server's updated record replaces
// what is shown, so the page never shows a state the server did not confirm.
export default function FindingPage() {
  const { project } = useOutletContext()
  const { findingId } = useParams()
  const api = useApi()
  const [loaded, reload] = useLoad(useCallback(() => api.getFinding(findingId), [api, findingId]))
  const [updated, setUpdated] = useState(null)
  const finding = updated && updated.id === findingId ? updated : loaded.data
  return (
    <>
      <p><Link to={`/projects/${project.id}/findings`}>Back to all findings</Link></p>
      <DataState state={loaded} onRetry={reload} what="this finding" loadingLabel="Loading finding…" isEmpty={() => false}>
        {() => (
          <>
            <PageHeaderLite title={finding.title} />
            <FindingDetailView finding={finding} api={api} projectId={project.id} onChanged={setUpdated} />
            {canRun(project) && project.status === 'active' && <FindingAssist projectId={project.id} findingId={finding.id} api={api} />}
          </>
        )}
      </DataState>
    </>
  )
}
