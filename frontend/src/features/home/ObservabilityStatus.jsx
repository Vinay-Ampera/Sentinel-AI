import { AvailabilityBadge } from '../../components/StatusBadge.jsx'
import { LEVEL_ORDER, LEVELS, OBSERVABILITY } from './observability.js'
import './ObservabilityStatus.css'

const HEADING = { available: 'Available', partial: 'Partially available', unavailable: 'Not available' }

// Every observability and alert feature with its honest status, what it needs and where it
// stops. Read-only: no controls, so nothing here can be mistaken for a working feature.
export default function ObservabilityStatus() {
  return (
    <section id="observability" className="obs-status" aria-labelledby="obs-title">
      <p className="section-tag">04 // OBSERVABILITY AND ALERTS</p>
      <h2 id="obs-title">Observability and alerts: what works today</h2>
      <p className="muted">
        Each feature is marked by what has actually been built and checked, with the setup it needs and its limits. Alerts describe what Sentinel measured; they never claim a cause.
      </p>
      <dl className="obs-legend" aria-label="What the labels mean">
        {LEVEL_ORDER.map((level) => (
          <div key={level}>
            <dt><AvailabilityBadge level={level} /></dt>
            <dd>{LEVELS[level]}</dd>
          </div>
        ))}
      </dl>
      {LEVEL_ORDER.map((level) => {
        const items = OBSERVABILITY.filter((f) => f.level === level)
        return (
          <div key={level} className="obs-group">
            <h3 id={`obs-${level}`}>{HEADING[level]} ({items.length})</h3>
            <ul className={`obs-list obs-list-${level}`} aria-labelledby={`obs-${level}`}>
              {items.map((f) => <Feature key={f.id} item={f} />)}
            </ul>
          </div>
        )
      })}
    </section>
  )
}

function Feature({ item }) {
  return (
    <li className="obs-item" data-level={item.level}>
      <div className="obs-head">
        <h4>{item.title}</h4>
        <AvailabilityBadge level={item.level} />
      </div>
      <p>{item.text}</p>
      {item.needs && (
        <p className="obs-detail"><strong>Needs:</strong> {item.needs}</p>
      )}
      <p className="obs-detail"><strong>{item.level === 'unavailable' ? 'Status:' : 'Limits:'}</strong> {item.limits}</p>
    </li>
  )
}
