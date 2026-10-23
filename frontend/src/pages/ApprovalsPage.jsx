import { useCallback, useState } from 'react'
import Alert from '../components/Alert.jsx'
import Field from '../components/Field.jsx'
import PageHeader from '../components/PageHeader.jsx'
import { DataState, EmptyState } from '../components/states.jsx'
import ApprovalDecisionDialog from '../features/approvals/ApprovalDecisionDialog.jsx'
import ApprovalList from '../features/approvals/ApprovalList.jsx'
import { useApi } from '../hooks/useApi.js'
import { useLoad } from '../hooks/useLoad.js'
import { useToast } from '../hooks/useToast.js'
import './ApprovalsPage.css'

const FILTERS = { pending: 'Waiting for a decision', approved: 'Approved', rejected: 'Rejected', all: 'All' }

export default function ApprovalsPage() {
  const api = useApi()
  const { notify } = useToast()
  const [status, setStatus] = useState('pending')
  const [deciding, setDeciding] = useState(null)
  const [approvals, reload] = useLoad(useCallback(() => api.listApprovals(status), [api, status]))
  const [projects] = useLoad(useCallback(() => api.listProjects(true), [api]))
  const names = Object.fromEntries((projects.data || []).map((p) => [p.id, p.name]))

  async function decided(decision) {
    notify({ tone: 'success', title: decision === 'approved' ? 'Approved' : 'Rejected', message: 'Your decision was recorded.' })
    setDeciding(null)
    reload()
  }

  return (
    <>
      <PageHeader title="Approvals" description="Requests that need a person's decision before anything runs." />
      <Alert tone="info">Approving a plan or a target does not run anything by itself. Test plans are reviewed on their own page; target authorizations are decided here.</Alert>
      <Field as="select" label="Show" value={status} onChange={(e) => setStatus(e.target.value)} className="approvals-filter">
        {Object.entries(FILTERS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </Field>
      <DataState
        state={approvals}
        onRetry={reload}
        what="approvals"
        loadingLabel="Loading approvals…"
        empty={<EmptyState title={status === 'pending' ? 'Nothing is waiting for your decision' : 'No approvals to show'}>Only requests you are eligible to decide appear in the waiting list.</EmptyState>}
      >
        {(items) => <ApprovalList approvals={items} projectNames={names} onDecide={setDeciding} />}
      </DataState>
      {deciding && <ApprovalDecisionDialog approval={deciding} api={api} onClose={() => setDeciding(null)} onDecided={decided} />}
    </>
  )
}
