// Honest wording. A finished run is "Finished", not "passed": its results say what happened.
// Infrastructure outcomes are kept apart from test outcomes on purpose.
export const RESULT_STATUS = {
  passed: { label: 'Passed', note: '' },
  failed: { label: 'Failed', note: 'The tests ran and at least one failed' },
  error: { label: 'Error', note: 'The runner could not complete (not a clean pass or fail)' },
  skipped: { label: 'Skipped', note: 'Did not run: not applicable, no runner yet, or no tests found' },
  blocked: { label: 'Blocked', note: 'Refused before running by policy or safety checks' },
  timed_out: { label: 'Timed out', note: 'Stopped because it exceeded its time limit' },
  cancelled: { label: 'Cancelled', note: 'Stopped on request while running' },
  not_run: { label: 'Not run', note: 'Never started' },
  failed_to_start: { label: 'Could not start', note: 'Infrastructure problem: not a test failure' },
}

export const CASE_STATUS = { passed: 'Passed', failed: 'Failed', error: 'Error', skipped: 'Skipped' }

export const RUN_STATUS = {
  queued: 'Queued',
  dispatched: 'Starting',
  running: 'Running',
  cancel_requested: 'Cancelling…',
  completed: 'Finished (see results)',
  failed: 'Failed',
  cancelled: 'Cancelled',
  timed_out: 'Timed out',
  blocked: 'Blocked',
}

export const ACTIVE_RUN = new Set(['queued', 'dispatched', 'running', 'cancel_requested'])
export const CANCELLABLE_RUN = new Set(['queued', 'dispatched', 'running'])

export const resultLabel = (s) => (RESULT_STATUS[s] ? RESULT_STATUS[s].label : s)
export const resultNote = (s) => (RESULT_STATUS[s] ? RESULT_STATUS[s].note : '')
export const runLabel = (s) => RUN_STATUS[s] || s
export const caseLabel = (s) => CASE_STATUS[s] || s
