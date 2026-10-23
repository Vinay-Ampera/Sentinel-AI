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
