import { useState } from 'react'
import DataTable from '../../components/DataTable.jsx'
import Field from '../../components/Field.jsx'
import Pagination from '../../components/Pagination.jsx'
import StatusBadge from '../../components/StatusBadge.jsx'
import { EmptyState } from '../../components/states.jsx'
import { usePagination } from '../../hooks/usePagination.js'
import { formatDuration } from '../../lib/format.js'
import { CASE_STATUS } from './labels.js'
import './CaseTable.css'

// The individual test cases the project's own test report listed. Messages and traces come from
// the project, are untrusted, and are shown as plain text.
export default function CaseTable({ cases }) {
  const [status, setStatus] = useState('')
  const shown = status ? cases.filter((c) => c.status === status) : cases
  const paging = usePagination(shown, 25)
  const present = [...new Set(cases.map((c) => c.status))]
  return (
    <>
      <Field as="select" label="Outcome" value={status} onChange={(e) => setStatus(e.target.value)} className="case-filter">
        <option value="">All outcomes</option>
        {present.map((s) => <option key={s} value={s}>{CASE_STATUS[s] || s}</option>)}
      </Field>
      <DataTable
        caption="Test cases"
        rows={paging.pageItems}
        getRowKey={(c) => c.ordinal}
        empty={<EmptyState title="No cases match" />}
        columns={[
          { key: 'name', header: 'Test', render: (c) => <span className="mono">{c.classname ? `${c.classname}::` : ''}{c.name}</span> },
          { key: 'status', header: 'Outcome', render: (c) => <StatusBadge domain="result" value={c.status} /> },
          { key: 'duration', header: 'Duration', render: (c) => formatDuration(c.duration_ms ?? undefined) },
          {
            key: 'message',
            header: 'Message',
            render: (c) => (
              <>
                {c.message && <span className="case-message">{c.message}</span>}
                {c.detail && (
                  <details>
                    <summary>Details</summary>
                    <pre className="case-detail">{c.detail}</pre>
                  </details>
                )}
              </>
            ),
          },
        ]}
      />
      <Pagination page={paging.page} pageCount={paging.pageCount} onPageChange={paging.setPage} label="Case pages" />
    </>
  )
}
