import { useState } from 'react'
import Button from './Button.jsx'
import './EvidenceViewer.css'

const DEFAULT_LIMIT = 20000

// Evidence is untrusted text from a sandbox or a target project. It is only ever rendered
// as plain text (never HTML), capped by default so a huge log cannot freeze the page, and
// labelled so nobody mistakes it for something Sentinel AI wrote.
export default function EvidenceViewer({ name, text, sizeBytes, limit = DEFAULT_LIMIT }) {
  const [showAll, setShowAll] = useState(false)
  const truncated = text.length > limit && !showAll
  const shown = truncated ? text.slice(0, limit) : text
  return (
    <figure className="evidence">
      <figcaption className="evidence-caption">
        <span className="evidence-name">{name || 'Evidence'}</span>
        {typeof sizeBytes === 'number' && <span className="muted">{sizeBytes} bytes</span>}
      </figcaption>
      <p className="evidence-note">Shown as plain text. This content comes from the tested project or tool and is not verified by Sentinel AI.</p>
      {text === '' ? (
        <p className="muted">This evidence file is empty.</p>
      ) : (
        <pre className="evidence-view" tabIndex={0} aria-label={`Contents of ${name || 'evidence'}`}>{shown}</pre>
      )}
      {truncated && (
        <p className="evidence-note">
          Showing the first {limit.toLocaleString()} of {text.length.toLocaleString()} characters.{' '}
          <Button size="sm" onClick={() => setShowAll(true)}>Show full text</Button>
        </p>
      )}
    </figure>
  )
}
