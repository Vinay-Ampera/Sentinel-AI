import './KeyValueList.css'

// A compact definition list for facts about one thing (project details, a run, an analysis).
// items: [{ label, value }]. Missing values show as "Not available" rather than a blank.
export default function KeyValueList({ items }) {
  return (
    <dl className="kv-list">
      {items.map((item) => (
        <div key={item.label} className="kv-row">
          <dt>{item.label}</dt>
          <dd>{item.value === null || item.value === undefined || item.value === '' ? <span className="muted">Not available</span> : item.value}</dd>
        </div>
      ))}
    </dl>
  )
}
