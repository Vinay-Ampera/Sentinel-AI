import { Link } from 'react-router-dom'
import DataTable from '../../components/DataTable.jsx'
import StatusBadge from '../../components/StatusBadge.jsx'
import { formatDate } from '../../lib/format.js'
import { accessLabel, typeLabel } from './labels.js'

export default function ProjectList({ projects }) {
  return (
    <DataTable
      caption="Projects"
      rows={projects}
      getRowKey={(p) => p.id}
      columns={[
        { key: 'name', header: 'Project', render: (p) => <Link to={`/projects/${p.id}`}>{p.name}</Link> },
        { key: 'type', header: 'Type', render: (p) => typeLabel(p.application_type) },
        { key: 'access', header: 'Your access', render: (p) => accessLabel(p.your_access) },
        { key: 'status', header: 'Status', render: (p) => <StatusBadge domain="project" value={p.status} /> },
        { key: 'updated', header: 'Updated', render: (p) => formatDate(p.updated_at) },
      ]}
    />
  )
}
