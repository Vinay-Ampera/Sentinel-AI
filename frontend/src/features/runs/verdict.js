import { ACTIVE_RUN } from './labels.js'

const count = (results, ...statuses) => results.filter((r) => statuses.includes(r.status)).length

// A plain-words summary of a run, computed only from recorded results. "Finished" is never
// "passed": a run is described as all-passed only when every expected check has a passed result,
// and anything that did not run is called out instead of being counted as fine.
// expected: how many checks the run should have produced results for (the run's tests_total).
export function runVerdict(run, results, expected) {
  if (ACTIVE_RUN.has(run.status)) {
    return { tone: 'info', title: run.status === 'cancel_requested' ? 'Cancelling' : 'Run in progress', text: 'Results appear as each check finishes. This page updates by itself.' }
  }
  if (run.status === 'failed') return { tone: 'danger', title: 'The run failed', text: run.error_summary || 'It did not complete. No error detail was recorded.' }
  if (run.status === 'blocked') return { tone: 'warning', title: 'The run was blocked', text: run.error_summary || 'Policy or safety checks refused it before anything ran.' }
  if (run.status === 'timed_out') return { tone: 'warning', title: 'The run timed out', text: run.error_summary || 'It was stopped at its time limit; some checks may not have finished.' }
  if (run.status === 'cancelled') return { tone: 'neutral', title: 'The run was cancelled', text: 'Checks that had not started were not run.' }

  const bad = count(results, 'failed', 'error', 'timed_out')
  const didNotRun = count(results, 'skipped', 'blocked', 'not_run', 'failed_to_start', 'cancelled')
  const passed = count(results, 'passed')
  if (bad > 0) {
    const parts = [['failed', 'failed'], ['error', 'errored'], ['timed_out', 'timed out']].map(([s, w]) => [count(results, s), w]).filter(([n]) => n > 0)
    return { tone: 'danger', title: `${bad} check${bad === 1 ? '' : 's'} did not pass`, text: parts.map(([n, w]) => `${n} ${w}`).join(', ') + '.' }
  }
  if (results.length === 0) return { tone: 'warning', title: 'Finished with no results recorded', text: 'Nothing here shows what ran.' }
  if (didNotRun > 0 || results.length < expected) {
    const missing = Math.max(0, expected - results.length)
    return { tone: 'warning', title: 'Finished, but not everything ran', text: `${passed} passed; ${didNotRun} did not run${missing ? `; ${missing} have no recorded result` : ''}.` }
  }
  return { tone: 'success', title: `All ${passed} check${passed === 1 ? '' : 's'} passed`, text: 'Passing means the checks that ran reported no failures. It does not mean the project has no bugs.' }
}
