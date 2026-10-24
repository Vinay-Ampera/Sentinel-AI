import { screen } from '@testing-library/react'
import { axe } from 'vitest-axe'
import { describe, expect, it } from 'vitest'
import { admin, fakeApi, project, renderApp } from './helpers.jsx'

// Structural accessibility checks (names, labels, roles, landmarks) on the signed-in pages that
// have the most forms and tables. Automated checks cannot prove accessibility, and colour
// contrast is covered separately by tokens.test.js (jsdom has no layout).
const options = { rules: { 'color-contrast': { enabled: false } } }

const finding = { id: 'f1', project_id: 'p1', title: 'B602 shell injection risk', severity: 'high', confidence: 'medium', verification_state: 'unverified', status: 'new', detected_by: 'bandit', file_path: 'app/db.py', line_number: 4, group_id: null, description: 'd', rule_id: 'B602', occurrences: 1, aliases: [], limitations: 'Static match.', events: [{ id: 1, event_type: 'created', from_value: null, to_value: 'new', detail: {}, created_at: '2026-10-20T10:00:00Z' }], evidence: [{ artifact_id: 'a1', filename: 'bandit.json', size_bytes: 10, kind: 'report' }], attempts: [], related: [] }
const source = { id: 's1', source_type: 'remote_url', name: 'Staging API', is_active: true, target_url: 'https://staging.example.com', environment: 'staging', created_at: '2026-10-20T10:00:00Z' }
const api = fakeApi({
  me: () => Promise.resolve(admin),
  listProjects: () => Promise.resolve([project]),
  getProject: () => Promise.resolve(project),
  listSources: () => Promise.resolve([source]),
  listMembers: () => Promise.resolve([{ user_id: 'u9', email: 'x@example.com', display_name: 'Xan', access_level: 'run', created_at: '2026-10-20T10:00:00Z' }]),
  listFindings: () => Promise.resolve([finding]),
  getFinding: () => Promise.resolve(finding),
  listAuthorizations: () => Promise.resolve([{ id: 'auth1', source_id: 's1', environment: 'staging', scope: { paths: ['/'], methods: ['GET'] }, allowed_risk: ['low'], status: 'approved', valid_until: '2026-11-01T00:00:00Z', in_effect: true }]),
  listApprovals: () => Promise.resolve([{ id: 'ap1', project_id: 'p1', kind: 'plan', plan_id: 'pl1', risk_level: 'low', decision: 'pending', created_at: '2026-10-20T10:00:00Z' }]),
  listUsers: () => Promise.resolve([{ id: 'u2', email: 'ada@example.com', display_name: 'Ada', role: 'admin', is_active: true, last_login_at: null }]),
  getRun: () => Promise.resolve({ id: 'r1', project_id: 'p1', plan_id: 'pl1', status: 'completed', timeout_seconds: 600, created_at: '2026-10-24T10:00:00Z', started_at: '2026-10-24T10:00:05Z', finished_at: '2026-10-24T10:01:05Z', error_summary: null, progress: { tests_total: 1, tests_finished: 1, results_by_status: { passed: 1 }, cases_by_status: { passed: 2 } } }),
  getPlan: () => Promise.resolve({ id: 'pl1', version: 1, tests: [{ id: 't1', name: 'Unit tests', tool: 'pytest', status: 'executed' }] }),
  listRunResults: () => Promise.resolve([{ id: 'x1', planned_test_id: 't1', attempt: 1, status: 'passed', summary: null, duration_ms: 900 }]),
  listRuns: () => Promise.resolve([{ id: 'r1', plan_id: 'pl1', status: 'completed', created_at: '2026-10-24T10:00:00Z', started_at: '2026-10-24T10:00:05Z', finished_at: '2026-10-24T10:01:05Z' }]),
  listAgentRuns: () => Promise.resolve([{ id: 'ar1', project_id: 'p1', workflow: 'planning', status: 'degraded', degraded_reason: 'llm_disabled', used_llm: false, cache_hit: false, model: null, plan_id: null, check_ids: [], source: null, message: null, result: { plan_id: null }, started_at: '2026-10-24T10:00:00Z', finished_at: '2026-10-24T10:00:01Z', steps: [{ seq: 1, node: 'deterministic_select', kind: 'deterministic', outcome: 'no_match', detail: {}, llm_usage_id: null }] }]),
  getAgentRun: () => Promise.resolve({ id: 'ar1', project_id: 'p1', workflow: 'planning', status: 'degraded', degraded_reason: 'llm_disabled', used_llm: false, cache_hit: false, model: null, plan_id: null, check_ids: [], source: null, message: null, result: { plan_id: null }, started_at: '2026-10-24T10:00:00Z', finished_at: '2026-10-24T10:00:01Z', steps: [{ seq: 1, node: 'deterministic_select', kind: 'deterministic', outcome: 'no_match', detail: {}, llm_usage_id: null }] }),
  listRegressionProposals: () => Promise.resolve([{ id: 'rp1', project_id: 'p1', finding_id: 'f1', result_id: null, status: 'proposed', title: 'Total includes tax', rationale: 'r', target_path: 'tests/test_a.py', framework: 'pytest', code: 'def test_a():\n    pass\n', expected_behavior: 'e', evidence_ids: ['finding:ab12cd34'], risk_flags: ['import os'], overlap: [], decided_by: null, decision_note: null, created_at: '2026-10-24T10:00:00Z', decided_at: null }]),
  listAlerts: () => Promise.resolve([{ id: 'al1', rule: 'new_error_group', rule_version: 'alert-rules-v1', source: 'external', severity: 'medium', status: 'open', title: 'New error group in api', measured: { events: 3 }, evidence: { group_id: 'g1' }, confidence: 'observed', cause_status: 'not_investigated', next_action: 'Open the group.', occurrences: 1, group_id: 'g1', run_id: null, result_id: null, finding_id: null, agent_run_id: null, first_seen: '2026-10-24T10:00:00Z', last_seen: '2026-10-24T10:05:00Z', closed_at: null }]),
  getTelemetryStatus: () => Promise.resolve({ ingest_enabled: true, active_keys: 1, has_events: true, last_event_at: '2026-10-24T10:00:00Z', events_last_24h_by_level: { error: 3 }, events_last_24h_by_environment: { staging: 3 }, dropped_last_24h: {}, evaluation_errors_last_24h: 0, groups: 1, share_of_groups_with_stack: 1, samples_with_trace_id: 0, samples_with_verified_link: 0, summary: 's', limits: ['Limit one.'] }),
  getAlert: () => Promise.resolve({ id: 'al1', rule: 'new_error_group', rule_version: 'alert-rules-v1', source: 'external', severity: 'medium', status: 'open', title: 'New error group in api', measured: { events: 3 }, evidence: { group_id: 'g1' }, confidence: 'observed', cause_status: 'not_investigated', next_action: 'Open the group.', occurrences: 1, group_id: 'g1', run_id: null, result_id: null, finding_id: null, agent_run_id: null, first_seen: '2026-10-24T10:00:00Z', last_seen: '2026-10-24T10:05:00Z', closed_at: null, history: [{ action: 'created', actor_user_id: null, note: null, detail: {}, created_at: '2026-10-24T10:00:00Z' }], group: null, proposal_ids: [], cause_note: 'No cause is claimed.', telemetry: { ingest_enabled: true, active_keys: 1, has_events: true, last_event_at: '2026-10-24T10:00:00Z', events_last_24h_by_level: { error: 3 }, events_last_24h_by_environment: {}, dropped_last_24h: {}, evaluation_errors_last_24h: 0, groups: 1, share_of_groups_with_stack: 1, samples_with_trace_id: 0, samples_with_verified_link: 0, summary: 's', limits: ['Limit one.'] } }),
  getEventGroup: () => Promise.resolve({ id: 'g1', service: 'api', environment: 'staging', level_class: 'error', error_type: 'E', message: 'boom <n>', first_seen: '2026-10-24T10:00:00Z', last_seen: '2026-10-24T10:05:00Z', total_count: 3, has_stack: true, is_overflow: false, fingerprint_version: 'fp-v1', limits: [], samples: [{ id: 's1', received_at: '2026-10-24T10:00:00Z', client_timestamp: null, timestamp_untrusted: false, level: 'error', service: 'api', environment: 'staging', message: 'boom', error_type: 'E', stack: null, attributes: {}, trace_id: null, span_id: null, release: null, correlation: {}, redactions: {} }] }),
  getTrace: () => Promise.resolve({ trace_id: 'ab'.repeat(16), runs: [{ id: 'r1', status: 'completed', plan_id: 'pl1', started_at: null, finished_at: null, created_at: '2026-10-24T10:00:00Z', trace_id: 'ab'.repeat(16) }], assistant_runs: [], events: [{ id: 'e1', received_at: '2026-10-24T10:00:01Z', service: 'api', level: 'error', message: 'boom' }], limits: ['Limit.'] }),
  getAlertThresholdLimits: () => Promise.resolve([{ name: 'new_group_events', default: 3, min: 1, max: 100, description: 'Events a new error group needs' }]),
  listIngestKeys: () => Promise.resolve([{ id: 'k1', key_id: 'abcdef012345', label: 'prod app', created_by: 'u1', created_at: '2026-10-24T10:00:00Z', expires_at: '2027-01-01T00:00:00Z', revoked_at: null, last_used_at: null, status: 'active' }]),
  listSessions: () => Promise.resolve([{ id: 'se1', created_at: '2026-10-20T10:00:00Z', last_seen_at: '2026-10-20T10:00:00Z', current: true, user_agent: 'Test', ip_address: null }]),
  getGlobalPolicies: () => Promise.resolve({ approval_required_risk_levels: ['high'], allowed_risk_levels: ['low'], high_risk_approver_roles: ['admin'], production_testing: { allowed: false } }),
})

describe('axe on signed-in pages', () => {
  it.each([
    ['/projects', 'Projects'],
    ['/projects/p1/setup', 'Sources'],
    ['/projects/p1/findings/f1', 'Review'],
    ['/projects/p1/governance', 'Target authorizations'],
    ['/projects/p1/runs/r1', 'Checks'],
    ['/projects/p1/runs', 'Run history'],
    ['/projects/p1/alerts', 'Event ingestion'],
    ['/projects/p1/alerts/al1', 'What was measured'],
    [`/projects/p1/traces/${'ab'.repeat(16)}`, 'Workflows with this trace id'],
    ['/projects/p1/assistant', 'Assistant runs'],
    ['/projects/p1/assistant/ar1', 'What happened, step by step'],
    ['/projects/p1/proposals', 'Total includes tax'],
    ['/approvals', 'Approvals'],
    ['/account', 'Active sessions'],
    ['/admin', 'Organization policy'],
  ])('%s', async (path, ready) => {
    const { container } = renderApp(api, path)
    await screen.findByRole('heading', { name: ready })
    await new Promise((r) => setTimeout(r, 50)) // let the page's own data settle
    expect(await axe(container, options)).toHaveNoViolations()
  })
})
