import { Link } from 'react-router-dom'
import StatusBadge from '../../components/StatusBadge.jsx'

// Groups of findings that several scanners report for one issue. They are linked, never merged:
// every member keeps its own tool, evidence and status.
export default function DuplicateGroups({ groups, projectId }) {
  const linked = groups.filter((g) => g.members.length > 1)
  if (linked.length === 0) return <p className="muted">No findings are reported by more than one scanner.</p>
  return (
    <ul className="dup-groups">
      {linked.map((g) => (
        <li key={g.id}>
          <p><strong>{g.members.length} findings, probably the same issue</strong> <span className="muted">(tools: {g.tools.join(', ')})</span> <StatusBadge domain="severity" value={g.severity} /></p>
          <ul>
            {g.members.map((m) => (
              <li key={m.id}>
                <Link to={`/projects/${projectId}/findings/${m.id}`}>{m.title}</Link> <span className="muted">{m.detected_by}</span> <StatusBadge domain="finding" value={m.status} />
              </li>
            ))}
          </ul>
        </li>
      ))}
    </ul>
  )
}
