import { AvailabilityBadge } from '../../components/StatusBadge.jsx'
import { CAPABILITIES } from './capabilities.js'
import './CapabilityGrid.css'

// Available and partly available capabilities first, then the planned ones, each labelled.
export default function CapabilityGrid() {
  const now = CAPABILITIES.filter((c) => c.level !== 'planned')
  const planned = CAPABILITIES.filter((c) => c.level === 'planned')
  return (
    <section id="capabilities" className="capabilities" aria-labelledby="capabilities-title">
      <p className="section-tag">03 // CAPABILITIES</p>
      <h2 id="capabilities-title">What it does today</h2>
      <ul className="capability-grid">
        {now.map((c) => <CapabilityItem key={c.id} item={c} />)}
      </ul>
      <h2 id="planned-title" className="capabilities-planned-title">Planned, not built yet</h2>
      <p className="muted">These are designed but are not available. Nothing here can be used yet.</p>
      <ul className="capability-grid capability-grid-planned" aria-labelledby="planned-title">
        {planned.map((c) => <CapabilityItem key={c.id} item={c} />)}
      </ul>
    </section>
  )
}

function CapabilityItem({ item }) {
  return (
    <li className="capability">
      <div className="capability-head">
        <h3>{item.title}</h3>
        <AvailabilityBadge level={item.level} stage={item.stage} when={item.when} />
      </div>
      <p>{item.text}</p>
    </li>
  )
}
