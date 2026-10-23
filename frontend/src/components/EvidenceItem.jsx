import { useState } from 'react'
import { describeError } from '../lib/errors.js'
import { formatBytes } from '../lib/format.js'
import Alert from './Alert.jsx'
import Button from './Button.jsx'
import EvidenceViewer from './EvidenceViewer.jsx'

// One piece of evidence (a finding's or a run's). It is fetched only when asked for, shown as
// plain text, and can be downloaded. Accepts either record shape: { artifact_id, filename } or
// { id, name }.
export default function EvidenceItem({ api, item }) {
  const [view, setView] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const id = item.artifact_id || item.id
  const name = item.filename || item.name || 'evidence'
  async function open() {
    setBusy(true)
    setError(null)
    try {
      setView(await api.getEvidenceText(id))
    } catch (e) {
      setError(describeError(e).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <li className="evidence-item">
      <span>{name} <span className="muted">({formatBytes(item.size_bytes)})</span></span>{' '}
      <Button size="sm" onClick={open} loading={busy} loadingLabel="Loading…" aria-label={`View ${name}`}>View</Button>{' '}
      {api.evidenceUrl && <a href={api.evidenceUrl(id)} download className="evidence-download" aria-label={`Download ${name}`}>Download</a>}
      {item.sha256 && <span className="muted evidence-hash"> sha256 {item.sha256.slice(0, 12)}…</span>}
      {error && <Alert tone="danger">{error}</Alert>}
      {view && <EvidenceViewer name={name} text={view.text} sizeBytes={item.size_bytes} />}
      {view && view.truncated && <p className="muted">Only the start of this file is shown here; download it for the rest.</p>}
    </li>
  )
}
