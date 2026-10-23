import { useState } from 'react'
import { Link } from 'react-router-dom'
import DataTable from '../../components/DataTable.jsx'
import Field from '../../components/Field.jsx'
import Pagination from '../../components/Pagination.jsx'
import StatusBadge from '../../components/StatusBadge.jsx'
import { EmptyState } from '../../components/states.jsx'
import { usePagination } from '../../hooks/usePagination.js'
import { formatDuration } from '../../lib/format.js'
import { RESULT_STATUS } from './labels.js'
import './ResultTable.css'

const NO_RESULT = 'no_result'
// Outcomes whose meaning is easy to misread get their one-line explanation shown.
const EXPLAIN = new Set(['failed_to_start', 'blocked', 'not_run', 'skipped', 'timed_out', 'error'])

// One row per check the run should have covered: its recorded result, or "no result recorded".
// rows: [{ key, name, tool, result | null }]. Filters work on what is loaded.
export default function ResultTable({ rows, projectId, runId, runActive }) {
  const [status, setStatus] = useState('')
  const [q, setQ] = useState('')
  const shown = rows.filter((r) => (status === '' ? true : status === NO_RESULT ? !r.result : r.result && r.result.status === status) && r.name.toLowerCase().includes(q.trim().toLowerCase()))
  const present = [...new Set(rows.filter((r) => r.result).map((r) => r.result.status))]
  const paging = usePagination(shown, 25)

  return (
    <>
      <div className="result-filters">
        <Field as="select" label="Outcome" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All outcomes</option>
          {present.map((s) => <option key={s} value={s}>{RESULT_STATUS[s] ? RESULT_STATUS[s].label : s}</option>)}
          {rows.some((r) => !r.result) && <option value={NO_RESULT}>No result recorded</option>}
        </Field>
        <Field label="Find a check" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <DataTable
        caption="Check results"
        rows={paging.pageItems}
        getRowKey={(r) => r.key}
        empty={<EmptyState title={rows.length === 0 ? 'No checks to show' : 'No checks match'}>{rows.length === 0 ? 'The plan for this run lists no runnable checks, or its details could not be read.' : 'Change the filters to see more.'}</EmptyState>}
        columns={[
          { key: 'name', header: 'Check', render: (r) => <><strong>{r.name}</strong>{r.tool && <><br /><span className="muted">{r.tool}</span></>}</> },
          {
            key: 'outcome',
            header: 'Outcome',
            render: (r) => (r.result ? <StatusBadge domain="result" value={r.result.status} showNote={EXPLAIN.has(r.result.status)} /> : <span className="muted">{runActive ? 'Waiting for a result' : 'No result recorded'}</span>),
          },
          { key: 'duration', header: 'Duration', render: (r) => (r.result ? formatDuration(r.result.duration_ms ?? undefined) : '') },
          { key: 'attempt', header: 'Attempt', render: (r) => (r.result ? r.result.attempt : '') },
          { key: 'summary', header: 'Summary', render: (r) => (r.result && r.result.summary ? <span className="result-summary">{r.result.summary}</span> : '') },
          { key: 'open', header: <span className="visually-hidden">Details</span>, render: (r) => (r.result ? <Link to={`/projects/${projectId}/runs/${runId}/results/${r.result.id}`} aria-label={`Details for ${r.name}`}>Details</Link> : null) },
        ]}
      />
      <Pagination page={paging.page} pageCount={paging.pageCount} onPageChange={paging.setPage} label="Result pages" />
    </>
  )
}
