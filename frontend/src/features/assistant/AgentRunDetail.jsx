import { Link } from 'react-router-dom'
import Alert from '../../components/Alert.jsx'
import Card from '../../components/Card.jsx'
import DataTable from '../../components/DataTable.jsx'
import KeyValueList from '../../components/KeyValueList.jsx'
import StatusBadge from '../../components/StatusBadge.jsx'
import { formatDateTime } from '../../lib/format.js'
import { CAUSE_LABEL, CLAIM_LABEL, SOURCE, STEP_KIND, VERDICT, degradedLabel, workflowLabel } from './labels.js'
import './AgentRunDetail.css'

// Everything below that came from a model is plain text from the model: it is shown as
// suggestion or hypothesis and never styled as a result, a pass or a confirmed finding.
function List({ items, render }) {
  return items && items.length > 0 ? <ul>{items.map(render)}</ul> : null
}

function Evidence({ ids }) {
  return ids && ids.length > 0 ? <span className="muted"> Based on: {ids.join(', ')}</span> : null
}

function Claims({ title, items, textKey }) {
  if (!items || items.length === 0) return null
  return (
    <>
      <h3>{title}</h3>
      <List items={items} render={(c, i) => (
        <li key={i}>
          <strong>{c.name || ''}</strong> {c[textKey]} <span className="muted">({CLAIM_LABEL[c.label] || c.label})</span>
          <Evidence ids={c.basis} />
        </li>
      )} />
    </>
  )
}

function Result({ run, projectId }) {
  const r = run.result || {}
  const plan = r.plan_id && <p><Link to={`/projects/${projectId}/plans/${r.plan_id}`}>Open the draft plan</Link>. It still needs your review, submission and approval before anything runs.</p>
  switch (run.workflow) {
    case 'planning':
      return (
        <>
          {r.source && <p>{SOURCE[r.source] || r.source}.</p>}
          {plan}
          <List items={Object.entries(r.reasons || {})} render={([id, why]) => <li key={id}><strong>{id}</strong>: {why}</li>} />
          {!r.plan_id && r.message && <p>{r.message}</p>}
        </>
      )
    case 'analysis': {
      const o = r.output
      return o ? (
        <>
          <p>{o.summary}<Evidence ids={o.summary_basis} /></p>
          <Claims title="Components" items={o.components} textKey="description" />
          <Claims title="Likely trust boundaries" items={o.trust_boundaries} textKey="description" />
          <Claims title="Uncertainties" items={o.uncertainties} textKey="statement" />
          <p className="muted">The facts, inferences and gaps on the Analysis tab are unchanged. This is an interpretation of them.</p>
        </>
      ) : <p>{r.message || 'No interpretation was produced.'}</p>
    }
    case 'investigation':
      return (
        <>
          <p><strong>Failure type (decided by built-in rules):</strong> {String(r.classification || '').replace(/_/g, ' ')}. {r.explanation}</p>
          {r.limitations && <Alert tone="warning" title="Limits">{r.limitations}</Alert>}
          <Claims title="Possible causes" items={(r.causes || []).map((c) => ({ ...c, name: CAUSE_LABEL[c.label] || c.label, label: c.label === 'likely' ? 'inference' : 'hypothesis', description: c.statement, basis: c.evidence_ids }))} textKey="description" />
          {(r.causes || []).some((c) => c.reproduction_steps && c.reproduction_steps.length > 0) && <p className="muted">Suggested reproduction steps are listed with each cause in the trace data; nothing was re-run.</p>}
          {r.message && <p>{r.message}</p>}
        </>
      )
    case 'regression':
      return r.proposal_id ? (
        <p>A test was drafted. <Link to={`/projects/${projectId}/proposals`}>Review it on the Proposals tab</Link>. Sentinel does not add it to your project, commit it or run it.</p>
      ) : (
        <p>{r.eligible === false ? `No test was drafted: ${r.reason}` : 'No test was drafted.'}</p>
      )
    case 'verification':
      return r.verdict ? (
        <>
          <p><strong>{VERDICT[r.verdict] || r.verdict}.</strong> {r.reason}</p>
          <List items={r.limitations} render={(l, i) => <li key={i}>{l}</li>} />
          {r.output && <p>{r.output.outcome_text}</p>}
        </>
      ) : (
        <>
          {r.eligible === false ? <p>No re-scan was prepared: {r.reason}</p> : plan}
        </>
      )
    default:
      return null
  }
}

export default function AgentRunDetail({ run, projectId }) {
  return (
    <>
      <Card title={workflowLabel(run.workflow)}>
        <KeyValueList
          items={[
            { label: 'Outcome', value: <StatusBadge domain="agent" value={run.status} /> },
            { label: 'Model', value: run.cache_hit ? 'Reused an earlier identical answer' : run.used_llm ? `Used (${run.model || 'model'})` : 'Not used: built-in rules were enough' },
            { label: 'Started', value: formatDateTime(run.started_at) },
            { label: 'Finished', value: formatDateTime(run.finished_at) },
          ]}
        />
        {run.status === 'degraded' && <Alert tone="warning" title="The model part did not complete">{degradedLabel(run.degraded_reason)} Anything built-in is still shown below.</Alert>}
        {run.status === 'failed' && <Alert tone="danger" title="This run failed">{(run.result && run.result.error) || 'It did not finish.'} Nothing was changed.</Alert>}
        <div className="agent-result"><Result run={run} projectId={projectId} /></div>
        <p className="muted">Model output is a suggestion built from stored evidence. It cannot approve, run or change anything.</p>
      </Card>
      <Card title="What happened, step by step">
        <DataTable
          caption="Steps"
          rows={run.steps || []}
          getRowKey={(s) => s.seq}
          columns={[
            { key: 'seq', header: '#' },
            { key: 'node', header: 'Step', render: (s) => s.node.replace(/_/g, ' ') },
            { key: 'kind', header: 'Kind', render: (s) => STEP_KIND[s.kind] || s.kind },
            { key: 'outcome', header: 'Outcome', render: (s) => s.outcome.replace(/_/g, ' ') },
          ]}
        />
      </Card>
    </>
  )
}
