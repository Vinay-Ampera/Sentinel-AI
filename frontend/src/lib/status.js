// One vocabulary for every status shown in the UI. Wording comes from the feature label
// modules (which are deliberately honest); this file adds the tone and icon so a status is
// never conveyed by colour alone. Unknown values render neutral with their raw text: the UI
// never guesses a favourable state.
import { RESULT_STATUS, RUN_STATUS } from '../features/runs/labels.js'
import { SEVERITY, STATUS as FINDING_STATUS, VERIFICATION } from '../features/findings/labels.js'
import { PLAN_STATUS, TEST_STATUS } from '../features/plans/labels.js'

// Tones map to tokens: success | danger | warning | info | neutral.
const RESULT = {
  passed: ['success', 'check'],
  failed: ['danger', 'cross'],
  error: ['danger', 'alert'],
  skipped: ['neutral', 'minus'],
  blocked: ['warning', 'ban'],
  timed_out: ['warning', 'clock'],
  cancelled: ['neutral', 'stop'],
  not_run: ['neutral', 'circle'],
  failed_to_start: ['warning', 'power'],
}

const RUN = {
  queued: ['neutral', 'clock'],
  dispatched: ['info', 'play'],
  running: ['info', 'play'],
  cancel_requested: ['warning', 'stop'],
  completed: ['neutral', 'flag'], // finished is not passed: results carry the outcome
  failed: ['danger', 'cross'],
  cancelled: ['neutral', 'stop'],
  timed_out: ['warning', 'clock'],
  blocked: ['warning', 'ban'],
}

const SEVERITY_TONE = {
  critical: ['danger', 'alert'],
  high: ['danger', 'alert'],
  medium: ['warning', 'alert'],
  low: ['info', 'info'],
  info: ['neutral', 'info'],
}

// Verification describes what is known, not whether it is good or bad.
const VERIFY = {
  unverified: ['neutral', 'circle'],
  likely: ['info', 'info'],
  confirmed: ['info', 'check'],
  not_reproduced: ['neutral', 'minus'],
  inconclusive: ['warning', 'alert'],
}

const FINDING = {
  new: ['info', 'dot'],
  triaged: ['info', 'dot'],
  in_progress: ['info', 'play'],
  fixed: ['warning', 'flag'], // claimed fixed, not yet re-checked by a scan
  verified_fixed: ['success', 'check'],
  accepted_risk: ['warning', 'flag'],
  false_positive: ['neutral', 'minus'],
  reopened: ['danger', 'alert'],
}

const PLAN = {
  draft: ['neutral', 'dot'],
  pending_approval: ['warning', 'clock'],
  approved: ['info', 'check'], // approved is not executed
  rejected: ['danger', 'cross'],
  superseded: ['neutral', 'minus'],
}

const TEST = {
  planned: ['info', 'dot'],
  approved: ['info', 'check'],
  skipped: ['neutral', 'minus'],
  deferred: ['warning', 'clock'],
  blocked: ['warning', 'ban'],
  executed: ['neutral', 'flag'],
  failed_to_start: ['warning', 'power'],
}

const APPROVAL = {
  pending: ['warning', 'clock'],
  approved: ['success', 'check'],
  rejected: ['danger', 'cross'],
  revoked: ['neutral', 'ban'],
}

const PROJECT = {
  active: ['info', 'dot'],
  archived: ['neutral', 'minus'],
}

// A finished analysis is a fact about what was inspected, not a verdict on the project.
const ANALYSIS = {
  completed: ['neutral', 'flag'],
  failed: ['danger', 'cross'],
}

const RISK = {
  low: ['neutral', 'dot'],
  medium: ['warning', 'alert'],
  high: ['danger', 'alert'],
  critical: ['danger', 'alert'],
}

// A finished assistant run is not a verdict: "partly completed" means a model step was
// unavailable or refused, and the built-in part of the result is still shown.
const AGENT = {
  running: ['info', 'play'],
  succeeded: ['neutral', 'flag'],
  degraded: ['warning', 'alert'],
  failed: ['danger', 'cross'],
}
const AGENT_LABEL = { running: 'Running', succeeded: 'Finished', degraded: 'Partly completed', failed: 'Failed' }

// A proposal is text for review: accepting it records a decision, it is never "passed".
const PROPOSAL = {
  proposed: ['info', 'dot'],
  accepted: ['neutral', 'check'],
  rejected: ['neutral', 'cross'],
  verified: ['info', 'check'],
}

const titleCase = (s) => String(s).replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())

function lookup(table, labelOf, noteOf = () => '') {
  return (value) => {
    const entry = table[value]
    return {
      label: labelOf(value),
      note: noteOf(value),
      tone: entry ? entry[0] : 'neutral',
      icon: entry ? entry[1] : 'circle',
    }
  }
}

const DOMAINS = {
  result: lookup(RESULT, (v) => (RESULT_STATUS[v] ? RESULT_STATUS[v].label : titleCase(v)), (v) => (RESULT_STATUS[v] ? RESULT_STATUS[v].note : '')),
  run: lookup(RUN, (v) => RUN_STATUS[v] || titleCase(v)),
  severity: lookup(SEVERITY_TONE, (v) => SEVERITY[v] || titleCase(v)),
  verification: lookup(VERIFY, (v) => (VERIFICATION[v] ? VERIFICATION[v].label : titleCase(v)), (v) => (VERIFICATION[v] ? VERIFICATION[v].note : '')),
  finding: lookup(FINDING, (v) => FINDING_STATUS[v] || titleCase(v)),
  plan: lookup(PLAN, (v) => PLAN_STATUS[v] || titleCase(v)),
  test: lookup(TEST, (v) => (TEST_STATUS[v] ? TEST_STATUS[v].label : titleCase(v)), (v) => (TEST_STATUS[v] ? TEST_STATUS[v].note : '')),
  approval: lookup(APPROVAL, titleCase),
  risk: lookup(RISK, (v) => `${titleCase(v)} risk`),
  project: lookup(PROJECT, titleCase),
  agent: lookup(AGENT, (v) => AGENT_LABEL[v] || titleCase(v)),
  proposal: lookup(PROPOSAL, titleCase),
  analysis: lookup(ANALYSIS, (v) => (v === 'completed' ? 'Completed' : titleCase(v))),
}

export const STATUS_DOMAINS = Object.keys(DOMAINS)

export function statusMeta(domain, value) {
  const lookupFn = DOMAINS[domain]
  if (!lookupFn) throw new Error(`Unknown status domain: ${domain}`)
  return lookupFn(value)
}

// Exposed so tests can assert that every known value has a deliberate tone and icon.
export const STATUS_TABLES = { result: RESULT, run: RUN, severity: SEVERITY_TONE, verification: VERIFY, finding: FINDING, plan: PLAN, test: TEST, approval: APPROVAL, risk: RISK, project: PROJECT, analysis: ANALYSIS, agent: AGENT, proposal: PROPOSAL }
