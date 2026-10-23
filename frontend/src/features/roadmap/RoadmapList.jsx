import { AvailabilityBadge } from '../../components/StatusBadge.jsx'
import { ROADMAP } from './roadmap.js'
import './RoadmapList.css'

// Planned work as a dashed grid: visibly "not here yet". Read-only: no buttons, no links.
export default function RoadmapList() {
  return (
    <ul className="roadmap-grid">
      {ROADMAP.map((r) => (
        <li key={r.stage} className="roadmap-item">
          <div className="roadmap-head">
            <h3>{r.title}</h3>
            <AvailabilityBadge level="planned" stage={r.stage} />
          </div>
          {r.note && <p className="roadmap-note">{r.note}</p>}
          <p>{r.text}</p>
          <ul>{r.items.map((i) => <li key={i}>{i}</li>)}</ul>
        </li>
      ))}
    </ul>
  )
}
