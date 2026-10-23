import { Link } from 'react-router-dom'
import DataTable from '../../components/DataTable.jsx'
import StatusBadge from '../../components/StatusBadge.jsx'
import { EmptyState } from '../../components/states.jsx'
import { confidenceLabel } from './labels.js'

function location(f) {
  if (!f.file_path) return f.component || null
  return `${f.file_path}${f.line_number ? `:${f.line_number}` : ''}`
}

// Severity (how bad it would be), the tool's own confidence (how sure the tool is) and the
// verification state (whether a person has checked) are three separate columns on purpose.
export default function FindingTable({ findings, projectId }) {
  return (
    <DataTable
      caption="Security findings"
      rows={findings}
      getRowKey={(f) => f.id}
      empty={<EmptyState title="No findings match">Nothing is stored for this view. That does not mean the code was scanned and found clean.</EmptyState>}
      columns={[
        {
          key: 'title',
          header: 'Finding',
          render: (f) => (
            <>
              <Link to={`/projects/${projectId}/findings/${f.id}`}>{f.title}</Link>
              {f.group_id && <><br /><span className="muted">Also reported by another scanner or advisory</span></>}
            </>
          ),
        },
        { key: 'severity', header: 'Severity', render: (f) => <StatusBadge domain="severity" value={f.severity} /> },
        { key: 'confidence', header: 'Tool confidence', render: (f) => confidenceLabel(f.confidence) },
        { key: 'verification', header: 'Verification', render: (f) => <StatusBadge domain="verification" value={f.verification_state} /> },
        { key: 'status', header: 'Status', render: (f) => <StatusBadge domain="finding" value={f.status} /> },
        { key: 'tool', header: 'Reported by', render: (f) => f.detected_by || 'Unknown' },
        { key: 'where', header: 'Location', render: (f) => <span className="mono">{location(f) || 'Not recorded'}</span> },
      ]}
    />
  )
}
