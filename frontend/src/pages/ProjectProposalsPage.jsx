import { useCallback, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import Alert from '../components/Alert.jsx'
import SectionHeader from '../components/SectionHeader.jsx'
import { DataState, EmptyState } from '../components/states.jsx'
import { canRun } from '../features/assistant/labels.js'
import ProposalCard from '../features/assistant/ProposalCard.jsx'
import { useApi } from '../hooks/useApi.js'
import { useLoad } from '../hooks/useLoad.js'

// Regression tests drafted by the assistant, waiting for a person. A decision is recorded; the
// file is never added to the project, committed or run by Sentinel.
export default function ProjectProposalsPage() {
  const { project } = useOutletContext()
  const api = useApi()
  const [loaded, reload] = useLoad(useCallback(() => api.listRegressionProposals(project.id), [api, project.id]))
  const [updated, setUpdated] = useState({})
  return (
    <>
      <Alert tone="warning" title="Drafts for review">
        Accepting records your decision only. Sentinel does not add the test to your project, commit it or run it. Read the code before you use it.
      </Alert>
      <SectionHeader title="Drafted regression tests" />
      <DataState state={loaded} onRetry={reload} what="the regression proposals" loadingLabel="Loading proposals…" isEmpty={() => false}>
        {(items) =>
          items.length === 0 ? (
            <EmptyState title="No proposals yet">Ask the assistant to draft a regression test from a finding you have marked likely or confirmed.</EmptyState>
          ) : (
            items.map((p) => {
              const proposal = updated[p.id] || p
              return <ProposalCard key={p.id} proposal={proposal} api={api} projectId={project.id} canDecide={canRun(project)} onChanged={(next) => setUpdated((u) => ({ ...u, [next.id]: next }))} />
            })
          )
        }
      </DataState>
    </>
  )
}
