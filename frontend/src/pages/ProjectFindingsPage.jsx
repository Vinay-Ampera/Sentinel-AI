import { useCallback, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import Alert from '../components/Alert.jsx'
import Card, { Metric, MetricGrid } from '../components/Card.jsx'
import Field from '../components/Field.jsx'
import Pagination from '../components/Pagination.jsx'
import { DataState } from '../components/states.jsx'
import DuplicateGroups from '../features/findings/DuplicateGroups.jsx'
import FindingTable from '../features/findings/FindingTable.jsx'
import { SEVERITY, STATUS } from '../features/findings/labels.js'
import { useApi } from '../hooks/useApi.js'
import { useLoad } from '../hooks/useLoad.js'
import { usePagination } from '../hooks/usePagination.js'
import './ProjectFindingsPage.css'

const SEVERITY_ORDER = ['critical', 'high', 'medium', 'low', 'info']

// Findings for one project: filters, summary, the table, and linked duplicates. Status and
// severity filters go through the API; the tool filter works on what is loaded.
export default function ProjectFindingsPage() {
  const { project } = useOutletContext()
  const api = useApi()
  const [status, setStatus] = useState('')
  const [severity, setSeverity] = useState('')
  const [tool, setTool] = useState('')
  const [findings, reload] = useLoad(useCallback(() => api.listFindings(project.id, { status, severity }), [api, project.id, status, severity]))
  const [groups] = useLoad(useCallback(() => api.listFindingGroups(project.id), [api, project.id]))
  const all = findings.data || []
  const tools = [...new Set(all.map((f) => f.detected_by).filter(Boolean))].sort()
  const shown = tool ? all.filter((f) => f.detected_by === tool) : all
  const paging = usePagination(shown, 20)
  const bySeverity = SEVERITY_ORDER.map((s) => [s, shown.filter((f) => f.severity === s).length])

  return (
    <>
      <Alert tone="info" title="Findings are leads, not verdicts">
        They come from scanners (Bandit, Semgrep, the dependency audit and, where enabled, OWASP ZAP). A scanner never marks a finding confirmed, and a clean scan does not mean the code is secure.
      </Alert>

      <Card title="Findings">
        <div className="findings-filters">
          <Field as="select" label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All statuses</option>
            {Object.entries(STATUS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </Field>
          <Field as="select" label="Severity" value={severity} onChange={(e) => setSeverity(e.target.value)}>
            <option value="">All severities</option>
            {SEVERITY_ORDER.map((s) => <option key={s} value={s}>{SEVERITY[s]}</option>)}
          </Field>
          <Field as="select" label="Reported by" value={tool} onChange={(e) => setTool(e.target.value)}>
            <option value="">All tools</option>
            {tools.map((t) => <option key={t} value={t}>{t}</option>)}
          </Field>
        </div>
        <DataState state={findings} onRetry={reload} what="this project's findings" loadingLabel="Loading findings…" isEmpty={() => false}>
          {() => (
            <>
              <MetricGrid label="Findings in this view">
                <Metric label="Shown" value={shown.length} />
                <Metric label="Not yet verified by a person" value={shown.filter((f) => f.verification_state === 'unverified').length} />
                {bySeverity.filter(([, n]) => n > 0).map(([s, n]) => <Metric key={s} label={SEVERITY[s]} value={n} />)}
              </MetricGrid>
              <FindingTable findings={paging.pageItems} projectId={project.id} />
              <Pagination page={paging.page} pageCount={paging.pageCount} onPageChange={paging.setPage} label="Findings pages" />
            </>
          )}
        </DataState>
      </Card>

      <Card title="Linked duplicates">
        <DataState state={groups} what="duplicate groups" loadingLabel="Loading…" isEmpty={() => false}>
          {(items) => <DuplicateGroups groups={items} projectId={project.id} />}
        </DataState>
      </Card>
    </>
  )
}
