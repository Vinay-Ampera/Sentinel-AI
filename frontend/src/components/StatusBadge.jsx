import { statusMeta } from '../lib/status.js'
import Icon from './Icon.jsx'
import './StatusBadge.css'

// domain: result | run | severity | verification | finding | plan | test | approval | risk |
// agent | proposal | alert (see lib/status.js for the full list).
// Shows icon + text label; tone colour is reinforcement only. With showNote the one-line
// explanation (for example "Infrastructure problem: not a test failure") is shown too.
export default function StatusBadge({ domain, value, showNote = false }) {
  const meta = statusMeta(domain, value)
  return (
    <span className="status-wrap">
      <span className={`badge badge-${meta.tone}`}>
        <Icon name={meta.icon} size={14} />
        {meta.label}
      </span>
      {showNote && meta.note && <span className="status-note">{meta.note}</span>}
    </span>
  )
}

// Marks a feature that is designed but not built. Never styled like a working control.
export function PlannedBadge({ stage }) {
  return <span className="badge badge-planned">{stage ? `Planned · Stage ${stage}` : 'Planned'}</span>
}

// How far a capability goes today. Used on the public site and the roadmap so "available",
// "partly available" and "planned" are always worded the same way.
const AVAILABILITY = {
  available: { tone: 'success', icon: 'check', label: 'Available now' },
  partial: { tone: 'warning', icon: 'alert', label: 'Partly available' },
}

export function AvailabilityBadge({ level, stage }) {
  if (level === 'planned') return <PlannedBadge stage={stage} />
  const a = AVAILABILITY[level]
  return (
    <span className={`badge badge-${a.tone}`}>
      <Icon name={a.icon} size={14} />
      {a.label}
    </span>
  )
}
