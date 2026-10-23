import { formatDateTime, titleCase } from '../../lib/format.js'
import './RunEvents.css'

// The audit trail of what the platform did with this run, oldest first.
export default function RunEvents({ events }) {
  if (events.length === 0) return <p className="muted">No events were recorded.</p>
  return (
    <ol className="run-events">
      {events.map((e) => (
        <li key={e.id}>
          <span className="muted">{formatDateTime(e.created_at)}</span>{' '}
          <strong>{titleCase(e.event_type)}</strong>
          {e.to_status ? `: ${e.from_status ? `${e.from_status} → ` : ''}${e.to_status}` : ''}
          {e.detail && (e.detail.reason || e.detail.note) ? <span className="muted"> — {e.detail.reason || e.detail.note}</span> : null}
        </li>
      ))}
    </ol>
  )
}
