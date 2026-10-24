import { useCallback } from 'react'
import { Link } from 'react-router-dom'
import Alert from '../../components/Alert.jsx'
import Card from '../../components/Card.jsx'
import KeyValueList from '../../components/KeyValueList.jsx'
import { DataState } from '../../components/states.jsx'
import { useLoad } from '../../hooks/useLoad.js'
import { formatDateTime } from '../../lib/format.js'
import { LEVEL_LABEL } from './labels.js'
import './SamplesPanel.css'

// The error group behind an alert and a few redacted samples. Everything here is text the
// application reported; it is shown as plain text and may be wrong or incomplete.
export default function SamplesPanel({ projectId, groupId, api }) {
  const [loaded, reload] = useLoad(useCallback(() => api.getEventGroup(projectId, groupId), [api, projectId, groupId]))
  return (
    <DataState state={loaded} onRetry={reload} what="the reported events" loadingLabel="Loading reported events…" isEmpty={() => false}>
      {(g) => (
        <Card title="Reported error" headingLevel={3}>
          <Alert tone="info" title="Reported by the application">
            Sentinel did not observe these events itself. Known secret shapes were redacted before storage, but redaction is pattern based and can miss others.
          </Alert>
          <KeyValueList
            items={[
              { label: 'Service', value: g.service },
              { label: 'Environment', value: g.environment },
              { label: 'Level', value: LEVEL_LABEL[g.level_class] || g.level_class },
              { label: 'Error type', value: g.error_type },
              { label: 'Message pattern', value: g.message },
              { label: 'Events in total', value: String(g.total_count) },
              { label: 'First / last seen', value: `${formatDateTime(g.first_seen)} / ${formatDateTime(g.last_seen)}` },
            ]}
          />
          {g.samples.length === 0 && <p className="muted">No samples are kept any more (they expire after the retention period).</p>}
          {g.samples.map((s) => (
            <div key={s.id} className="sample">
              <p className="sample-head"><strong>{formatDateTime(s.received_at)}</strong>{s.release ? ` · release ${s.release}` : ''}</p>
              <pre className="sample-text" role="group" tabIndex={0} aria-label={`Reported event from ${formatDateTime(s.received_at)}`}>{[s.message, s.stack].filter(Boolean).join('\n\n')}</pre>
              {s.trace_id && <p className="muted">Trace <Link to={`/projects/${projectId}/traces/${s.trace_id}`}>{s.trace_id}</Link>: view the events and workflows that share it.</p>}
              {s.correlation && s.correlation.during_run && <p className="muted">Occurred while a test run was active (shown for context, not as a cause).</p>}
              {s.timestamp_untrusted && <p className="muted">The application's own timestamp was not trusted; the time shown is when Sentinel received it.</p>}
            </div>
          ))}
        </Card>
      )}
    </DataState>
  )
}
