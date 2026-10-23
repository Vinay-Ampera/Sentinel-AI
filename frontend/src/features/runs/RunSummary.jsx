import Alert from '../../components/Alert.jsx'
import Card, { Metric, MetricGrid, ProgressBar } from '../../components/Card.jsx'
import OutcomeBar from '../../components/OutcomeBar.jsx'
import StatusBadge from '../../components/StatusBadge.jsx'
import { durationBetween, formatDateTime, formatDuration, formatTime } from '../../lib/format.js'
import { ACTIVE_RUN } from './labels.js'
import { runVerdict } from './verdict.js'
import './RunSummary.css'

const countBy = (items, pick) => items.reduce((acc, i) => ({ ...acc, [pick(i)]: (acc[pick(i)] || 0) + 1 }), {})

// The top of the report: the verdict in words, key facts, how far the run got, and the outcome
// of every check and every case. Everything is computed from recorded results.
export default function RunSummary({ run, results, updatedAt }) {
  const p = run.progress
  const expected = p ? p.tests_total : results.length
  const verdict = runVerdict(run, results, expected)
  const active = ACTIVE_RUN.has(run.status)
  const duration = durationBetween(run.started_at, run.finished_at)
  return (
    <Card title="Summary">
      <Alert tone={verdict.tone} title={verdict.title}>{verdict.text}</Alert>
      <MetricGrid label="Run facts">
        <Metric label="Status" value={<StatusBadge domain="run" value={run.status} />} />
        <Metric label="Checks with a result" value={p ? `${p.tests_finished} of ${p.tests_total}` : 'Not available'} />
        <Metric label="Duration" value={active ? 'In progress' : formatDuration(duration ?? undefined)} />
        <Metric label="Started" value={run.started_at ? formatDateTime(run.started_at) : 'Not started'} />
        <Metric label="Finished" value={run.finished_at ? formatDateTime(run.finished_at) : active ? 'Not yet' : 'Not recorded'} />
        <Metric label="Time limit" value={formatDuration(run.timeout_seconds * 1000)} hint={`Last updated ${formatTime(updatedAt)}`} />
      </MetricGrid>
      {p && p.tests_total > 0 && <ProgressBar value={p.tests_finished} max={p.tests_total} label="Checks with a result" />}

      <div className="run-outcomes">
        <section aria-labelledby="outcome-checks">
          <h3 id="outcome-checks">Outcome of each check</h3>
          <OutcomeBar counts={countBy(results, (r) => r.status)} emptyText="No check has a result yet." />
        </section>
        <section aria-labelledby="outcome-cases">
          <h3 id="outcome-cases">Individual test cases</h3>
          <OutcomeBar counts={p ? p.cases_by_status : {}} emptyText="No individual test cases were reported." />
        </section>
      </div>
    </Card>
  )
}
