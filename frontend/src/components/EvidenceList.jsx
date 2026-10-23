import EvidenceItem from './EvidenceItem.jsx'
import './EvidenceList.css'

// A list of evidence items (a finding's or a run result's). items: [{ id | artifact_id, ... }].
export default function EvidenceList({ api, items }) {
  return (
    <ul className="evidence-list">
      {items.map((item) => <EvidenceItem key={item.artifact_id || item.id} api={api} item={item} />)}
    </ul>
  )
}
