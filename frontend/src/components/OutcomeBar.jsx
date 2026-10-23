import { statusMeta } from '../lib/status.js'
import StatusBadge from './StatusBadge.jsx'
import './OutcomeBar.css'

// A stacked bar of outcomes with a written legend. The bar is a quick visual; the legend (badge
// icon, label and count for every outcome) carries the information, so nothing depends on colour.
export default function OutcomeBar({ counts, domain = 'result', emptyText = 'Nothing recorded yet.' }) {
  const entries = Object.entries(counts || {}).filter(([, n]) => n > 0)
  const total = entries.reduce((sum, [, n]) => sum + n, 0)
  if (total === 0) return <p className="muted">{emptyText}</p>
  return (
    <div className="outcome">
      <div className="outcome-bar" aria-hidden="true">
        {entries.map(([status, n]) => (
          <span key={status} className={`outcome-seg outcome-${statusMeta(domain, status).tone}`} style={{ flexGrow: n }} />
        ))}
      </div>
      <ul className="outcome-legend">
        {entries.map(([status, n]) => (
          <li key={status}><StatusBadge domain={domain} value={status} /> <strong>{n}</strong></li>
        ))}
      </ul>
    </div>
  )
}
