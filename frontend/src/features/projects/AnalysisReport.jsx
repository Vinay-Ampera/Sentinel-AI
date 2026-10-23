import Alert from '../../components/Alert.jsx'
import KeyValueList from '../../components/KeyValueList.jsx'
import StatusBadge from '../../components/StatusBadge.jsx'
import { formatBytes, formatDateTime } from '../../lib/format.js'
import './AnalysisReport.css'

const names = (list) => (list && list.length ? list.map((x) => x.name).join(', ') : null)

// Shows an analysis in three honest layers: facts read from the archive, inferences drawn from
// them (with a confidence), and gaps (what could not be checked). No project code was run.
export default function AnalysisReport({ analysis }) {
  const r = analysis.result || {}
  const facts = r.facts || {}
  const archive = facts.archive || {}
  const tests = facts.test_files || { count: 0, examples: [] }
  return (
    <div className="analysis">
      <div className="analysis-head">
        <StatusBadge domain="analysis" value={analysis.status} />
        <span className="muted">Analysed {formatDateTime(analysis.completed_at || analysis.created_at)}</span>
      </div>
      {analysis.status === 'failed' && <Alert tone="danger" title="This analysis did not finish">{analysis.error_summary || 'No reason was recorded.'}</Alert>}
      <p className="muted">Static inspection of the uploaded archive. No project code was executed, so nothing here describes runtime behaviour, test results or coverage.</p>

      <h3>Facts found in the archive</h3>
      <KeyValueList
        items={[
          { label: 'Files', value: archive.file_count },
          { label: 'Size when unpacked', value: formatBytes(archive.total_uncompressed_bytes) },
          { label: 'Languages', value: facts.languages && facts.languages.length ? facts.languages.map((l) => `${l.name} (${l.files})`).join(', ') : null },
          { label: 'Frameworks', value: names(facts.frameworks) },
          { label: 'Test tools', value: names(facts.test_tools) },
          { label: 'Coverage tools', value: names(facts.coverage_tools) },
          { label: 'Test files', value: tests.count },
          { label: 'Lockfiles', value: facts.lockfiles && facts.lockfiles.length ? facts.lockfiles.join(', ') : null },
        ]}
      />
      {tests.examples && tests.examples.length > 0 && (
        <details className="analysis-details">
          <summary>Example test files ({tests.examples.length})</summary>
          <ul className="mono-list">{tests.examples.map((t) => <li key={t} className="mono">{t}</li>)}</ul>
        </details>
      )}
      {r.warnings && r.warnings.length > 0 && (
        <Alert tone="warning" title="Warnings">
          <ul>{r.warnings.map((w) => <li key={w.id}>{w.detail}</li>)}</ul>
        </Alert>
      )}

      <h3>Inferences</h3>
      {r.inferences && r.inferences.length > 0 ? (
        <ul className="analysis-list">
          {r.inferences.map((i) => (
            <li key={i.id}>
              {i.statement} <span className="badge">Confidence: {i.confidence}</span>
              {i.basis && i.basis.length > 0 && <div className="muted">Based on: {i.basis.join('; ')}</div>}
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">Nothing could be inferred from the facts.</p>
      )}

      <h3>Gaps: what this analysis cannot tell you</h3>
      {r.gaps && r.gaps.length > 0 ? (
        <ul className="analysis-list">
          {r.gaps.map((g) => (
            <li key={g.id}>
              <strong>{g.what}</strong>
              <span className="muted"> ({g.kind === 'coverage_gap' ? 'coverage gap' : 'evidence not available'})</span>
              <div className="muted">{g.why}</div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">No gaps were recorded.</p>
      )}
    </div>
  )
}
