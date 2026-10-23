import { Link } from 'react-router-dom'
import Alert from '../../components/Alert.jsx'
import Card from '../../components/Card.jsx'
import KeyValueList from '../../components/KeyValueList.jsx'
import StatusBadge from '../../components/StatusBadge.jsx'
import { formatDateTime } from '../../lib/format.js'
import EvidenceList from '../../components/EvidenceList.jsx'
import FindingReview from './FindingReview.jsx'
import { confidenceLabel, verificationNote } from './labels.js'
import './FindingDetailView.css'

// Everything known about one finding, with the limits stated: where it came from, how sure the
// tool was, what a person has judged, the evidence behind it, and its history.
export default function FindingDetailView({ finding: f, api, projectId, onChanged }) {
  return (
    <>
      <Card title="Summary">
        <p>{f.description || 'No description was recorded.'}</p>
        <div className="finding-badges">
          <StatusBadge domain="severity" value={f.severity} />
          <StatusBadge domain="verification" value={f.verification_state} showNote />
          <StatusBadge domain="finding" value={f.status} />
        </div>
        <KeyValueList
          items={[
            { label: 'Reported by', value: `${f.detected_by}${f.rule_id ? ` (${f.rule_id})` : ''}` },
            { label: 'Tool confidence', value: confidenceLabel(f.confidence) },
            { label: 'Location', value: f.file_path ? `${f.file_path}${f.line_number ? `:${f.line_number}` : ''}` : f.component },
            { label: 'Seen in', value: `${f.occurrences} scan${f.occurrences === 1 ? '' : 's'}` },
            { label: 'CWE', value: f.cwe ? `CWE-${f.cwe}` : null },
            { label: 'Also known as', value: f.aliases && f.aliases.length > 1 ? f.aliases.slice(1).join(', ') : null },
            { label: 'First recorded', value: formatDateTime(f.created_at) },
          ]}
        />
        {f.limitations && <Alert tone="warning" title="Limitations">{f.limitations}</Alert>}
        <p className="muted">{verificationNote(f.verification_state)}.</p>
      </Card>

      {f.related && f.related.length > 0 && (
        <Card title="Also reported by other scanners">
          <p className="muted">These probably describe the same issue. They are linked, not merged: each keeps its own tool, evidence and status.</p>
          <ul aria-label="Related findings">
            {f.related.map((r) => (
              <li key={r.id}>
                <Link to={`/projects/${projectId}/findings/${r.id}`}>{r.title}</Link> <span className="muted">{r.detected_by}</span> <StatusBadge domain="finding" value={r.status} />
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card title="Evidence">
        {f.evidence.length === 0 ? (
          <Alert tone="warning">No evidence is linked to this finding, so it cannot be confirmed.</Alert>
        ) : (
          <EvidenceList api={api} items={f.evidence} />
        )}
      </Card>

      <Card title="Verification attempts">
        {f.attempts.length === 0 ? (
          <p className="muted">None yet.</p>
        ) : (
          <ul>
            {f.attempts.map((a) => (
              <li key={a.id}>
                {a.method === 'rescan' ? 'Automatic re-scan' : 'Manual'}: {a.outcome.replace('_', ' ')}
                {a.notes ? <span className="muted"> — {a.notes}</span> : null}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="Review">
        <FindingReview finding={f} api={api} onChanged={onChanged} />
      </Card>

      <Card title="History">
        <ol className="finding-history">
          {f.events.map((e) => (
            <li key={e.id}>
              <strong>{e.event_type.replace('_', ' ')}</strong>
              {e.to_value ? `: ${e.from_value ? `${e.from_value} → ` : ''}${e.to_value}` : ''}
              {e.detail && e.detail.note ? <span className="muted"> — {e.detail.note}</span> : null}
              {e.created_at && <span className="muted"> · {formatDateTime(e.created_at)}</span>}
            </li>
          ))}
        </ol>
      </Card>
    </>
  )
}
