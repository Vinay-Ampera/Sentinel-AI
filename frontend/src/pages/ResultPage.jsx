import { useCallback } from 'react'
import { Link, useOutletContext, useParams } from 'react-router-dom'
import Card from '../components/Card.jsx'
import EvidenceList from '../components/EvidenceList.jsx'
import KeyValueList from '../components/KeyValueList.jsx'
import SectionHeader from '../components/SectionHeader.jsx'
import StatusBadge from '../components/StatusBadge.jsx'
import OutcomeBar from '../components/OutcomeBar.jsx'
import { DataState } from '../components/states.jsx'
import CaseTable from '../features/runs/CaseTable.jsx'
import { RESULT_STATUS } from '../features/runs/labels.js'
import { useApi } from '../hooks/useApi.js'
import { useLoad } from '../hooks/useLoad.js'
import { formatDateTime, formatDuration } from '../lib/format.js'

// One check's result: what it was, how it ended, the cases it reported, and the evidence behind
// it. Cases, messages and output come from the tested project and are untrusted plain text.
export default function ResultPage() {
  const { project } = useOutletContext()
  const { runId, resultId } = useParams()
  const api = useApi()
  const [state, reload] = useLoad(
    useCallback(async () => {
      const run = await api.getRun(runId)
      const [detail, plan] = await Promise.all([api.getRunResult(runId, resultId), api.getPlan(run.plan_id).catch(() => null)])
      return { detail, plan }
    }, [api, runId, resultId]),
  )
  return (
    <>
      <p><Link to={`/projects/${project.id}/runs/${runId}`}>Back to the run report</Link></p>
      <DataState state={state} onRetry={reload} what="this result" loadingLabel="Loading the result…" isEmpty={() => false}>
        {({ detail: d, plan }) => {
          const test = plan ? plan.tests.find((t) => t.id === d.planned_test_id) : null
          const counts = d.cases.reduce((acc, c) => ({ ...acc, [c.status]: (acc[c.status] || 0) + 1 }), {})
          return (
            <>
              <SectionHeader title={test ? test.name : 'Check result'} />
              <Card title="Result">
                <p><StatusBadge domain="result" value={d.status} showNote /></p>
                {d.summary && <p>{d.summary}</p>}
                <KeyValueList
                  items={[
                    { label: 'Tool', value: test ? test.tool : null },
                    { label: 'Category', value: test ? test.category : null },
                    { label: 'Risk', value: test ? test.risk_level : null },
                    { label: 'Attempt', value: d.attempt },
                    { label: 'Duration', value: formatDuration(d.duration_ms ?? undefined) },
                    { label: 'Exit code', value: d.exit_code === null || d.exit_code === undefined ? null : String(d.exit_code) },
                    { label: 'Finished', value: d.finished_at ? formatDateTime(d.finished_at) : null },
                  ]}
                />
                {!RESULT_STATUS[d.status] && <p className="muted">This outcome is not one the page knows; it is shown as the server reported it.</p>}
              </Card>
              <Card title="Test cases">
                {d.cases.length === 0 ? (
                  <p className="muted">This check reported no individual cases.</p>
                ) : (
                  <>
                    <OutcomeBar counts={counts} />
                    <CaseTable cases={d.cases} />
                  </>
                )}
              </Card>
              <Card title="Evidence">
                <p className="muted">Output from the sandbox is untrusted text. Secrets are redacted before it is stored.</p>
                {d.evidence.length === 0 ? <p>No evidence was stored for this check.</p> : <EvidenceList api={api} items={d.evidence} />}
              </Card>
            </>
          )
        }}
      </DataState>
    </>
  )
}
