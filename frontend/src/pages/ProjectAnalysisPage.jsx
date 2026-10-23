import { useCallback, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import Alert from '../components/Alert.jsx'
import Button from '../components/Button.jsx'
import Card from '../components/Card.jsx'
import DataTable from '../components/DataTable.jsx'
import Field from '../components/Field.jsx'
import StatusBadge from '../components/StatusBadge.jsx'
import { DataState, EmptyState } from '../components/states.jsx'
import AnalysisReport from '../features/projects/AnalysisReport.jsx'
import { ANALYSABLE_SOURCE, sourceTypeLabel } from '../features/projects/labels.js'
import { useApi } from '../hooks/useApi.js'
import { useLoad } from '../hooks/useLoad.js'
import { useToast } from '../hooks/useToast.js'
import { describeError } from '../lib/errors.js'
import { formatDateTime } from '../lib/format.js'
import './ProjectAnalysisPage.css'

export default function ProjectAnalysisPage() {
  const { project } = useOutletContext()
  const api = useApi()
  const { notify } = useToast()
  const pid = project.id
  const [analyses, reloadAnalyses] = useLoad(useCallback(() => api.listAnalyses(pid), [api, pid]))
  const [sources] = useLoad(useCallback(() => api.listSources(pid), [api, pid]))
  const [sourceId, setSourceId] = useState('')
  const [selectedId, setSelectedId] = useState(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState(null)

  const usable = (sources.data || []).filter((s) => s.is_active && ANALYSABLE_SOURCE.has(s.source_type))

  async function run() {
    setRunning(true)
    setError(null)
    try {
      const created = await api.runAnalysis(pid, sourceId || usable[0].id)
      notify({ tone: 'success', title: 'Analysis finished', message: created.status === 'failed' ? 'It did not complete; see the report.' : undefined })
      setSelectedId(created.id)
      reloadAnalyses()
    } catch (e) {
      setError(describeError(e).message)
    } finally {
      setRunning(false)
    }
  }

  return (
    <>
      <Card title="Run an analysis">
        <p className="muted">Reads the uploaded archive to detect languages, frameworks and test tooling. It does not run any project code.</p>
        {error && <Alert tone="danger" title="The analysis did not run">{error}</Alert>}
        <DataState state={sources} what="this project's sources" loadingLabel="Loading sources…" isEmpty={() => false}>
          {() =>
            usable.length === 0 ? (
              <EmptyState title="No analysable source">Add a ZIP upload on the Setup tab. Git, localhost and remote sources cannot be analysed yet.</EmptyState>
            ) : (
              <div className="analysis-run">
                <Field as="select" label="Source" value={sourceId || usable[0].id} onChange={(e) => setSourceId(e.target.value)}>
                  {usable.map((s) => <option key={s.id} value={s.id}>{s.name} ({sourceTypeLabel(s.source_type)})</option>)}
                </Field>
                <Button variant="primary" onClick={run} loading={running} loadingLabel="Analysing…" disabled={project.status === 'archived'} disabledReason="Archived projects cannot be analysed">
                  Run analysis
                </Button>
              </div>
            )
          }
        </DataState>
      </Card>

      <Card title="Analysis history">
        <DataState state={analyses} onRetry={reloadAnalyses} what="analyses" loadingLabel="Loading analyses…" empty={<EmptyState title="No analysis yet">Run one above to see what was detected.</EmptyState>}>
          {(items) => {
            const sorted = [...items].sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)))
            const selected = sorted.find((a) => a.id === selectedId) || sorted[0]
            return (
              <>
                <DataTable
                  caption="Analyses, newest first"
                  rows={sorted}
                  getRowKey={(a) => a.id}
                  columns={[
                    { key: 'when', header: 'Analysed', render: (a) => formatDateTime(a.created_at) },
                    { key: 'status', header: 'Result', render: (a) => <StatusBadge domain="analysis" value={a.status} /> },
                    { key: 'view', header: <span className="visually-hidden">View</span>, render: (a) => <Button size="sm" aria-pressed={a.id === selected.id} onClick={() => setSelectedId(a.id)}>{a.id === selected.id ? 'Showing' : 'Show report'}</Button> },
                  ]}
                />
                <h3 className="analysis-selected-title">Report from {formatDateTime(selected.created_at)}</h3>
                <AnalysisReport analysis={selected} />
              </>
            )
          }}
        </DataState>
      </Card>
    </>
  )
}
