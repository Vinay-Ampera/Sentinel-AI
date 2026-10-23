// Honest wording. Scanner output is a lead, not a verdict: "Unverified" stays on screen until
// a person says otherwise, and the tool's own confidence is shown apart from the severity.
export const SEVERITY = { critical: 'Critical', high: 'High', medium: 'Medium', low: 'Low', info: 'Info' }
export const CONFIDENCE = { high: 'High', medium: 'Medium', low: 'Low' }

export const VERIFICATION = {
  unverified: { label: 'Unverified', note: 'Reported by a scanner; nobody has checked it yet' },
  likely: { label: 'Likely (reviewer)', note: 'A reviewer thinks it is real' },
  confirmed: { label: 'Confirmed by a reviewer', note: 'A reviewer confirmed it, with evidence' },
  not_reproduced: { label: 'Not reproduced', note: 'A reviewer could not reproduce it' },
  inconclusive: { label: 'Inconclusive', note: 'A reviewer could not decide' },
}

export const STATUS = {
  new: 'New',
  triaged: 'Triaged',
  in_progress: 'In progress',
  fixed: 'Fixed (not yet verified by a later scan)',
  verified_fixed: 'Fixed (no longer reported by a later scan)',
  accepted_risk: 'Accepted risk',
  false_positive: 'False positive',
  reopened: 'Reopened',
}

// UX only: the server enforces who may do what and which transitions exist.
export const NEXT_STATUS = {
  new: ['triaged', 'in_progress', 'fixed', 'false_positive', 'accepted_risk'],
  triaged: ['in_progress', 'fixed', 'false_positive', 'accepted_risk'],
  in_progress: ['triaged', 'fixed', 'false_positive', 'accepted_risk'],
  reopened: ['triaged', 'in_progress', 'fixed', 'false_positive', 'accepted_risk'],
  fixed: ['reopened'],
  verified_fixed: ['reopened'],
  accepted_risk: ['triaged', 'reopened'],
  false_positive: ['triaged', 'reopened'],
}
export const NOTE_STATUSES = new Set(['false_positive', 'accepted_risk'])
export const MANUAL_VERIFICATION = ['likely', 'confirmed', 'not_reproduced', 'inconclusive']

export const severityLabel = (s) => SEVERITY[s] || s
export const confidenceLabel = (s) => CONFIDENCE[s] || s
export const verificationLabel = (s) => (VERIFICATION[s] ? VERIFICATION[s].label : s)
export const verificationNote = (s) => (VERIFICATION[s] ? VERIFICATION[s].note : '')
export const statusLabel = (s) => STATUS[s] || s
