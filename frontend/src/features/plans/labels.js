// Honest wording: nothing here has been executed, so no label implies a result.
export const TEST_STATUS = {
  planned: { label: 'Planned', note: 'Applicable; waiting for approval' },
  approved: { label: 'Approved', note: 'Eligible for a later run; not executed' },
  skipped: { label: 'Not applicable', note: 'Does not apply to this project' },
  deferred: { label: 'Unavailable', note: 'Applicable, but a prerequisite is missing' },
  blocked: { label: 'Blocked', note: 'Policy or target authorization prevents it' },
  executed: { label: 'Executed', note: '' },
  failed_to_start: { label: 'Failed to start', note: '' },
}

export const PLAN_STATUS = {
  draft: 'Draft: review and edit before submitting',
  pending_approval: 'Waiting for approval',
  approved: 'Approved (not run)',
  rejected: 'Rejected',
  superseded: 'Superseded',
}

export const statusLabel = (s) => (TEST_STATUS[s] ? TEST_STATUS[s].label : s)
export const planStatusLabel = (s) => PLAN_STATUS[s] || s
// Group order: what will happen first, then why other checks will not.
export const GROUPS = ['planned', 'approved', 'blocked', 'deferred', 'skipped', 'executed', 'failed_to_start']
