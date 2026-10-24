import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import App from '../src/app/App.jsx'

// Accessible description as a screen reader would compute it from aria-describedby.
export function describedBy(element) {
  return (element.getAttribute('aria-describedby') || '')
    .split(/\s+/)
    .filter(Boolean)
    .map((id) => document.getElementById(id)?.textContent ?? '')
    .join(' ')
    .trim()
}


export const user = { id: 'u1', email: 'dana@example.com', display_name: 'Dana Dev', role: 'developer' }
export const admin = { id: 'u2', email: 'ada@example.com', display_name: 'Ada Admin', role: 'admin' }
export const project = { id: 'p1', name: 'Shop', description: null, status: 'active', application_type: 'web_app', your_access: 'manage', updated_at: '2026-10-20T10:00:00Z', created_at: '2026-10-20T10:00:00Z' }

// A fake API: every method resolves with an empty answer unless a test overrides it, so a page
// that makes an extra call does not crash the test.
export function fakeApi(over = {}) {
  const empty = () => Promise.resolve([])
  return {
    me: () => Promise.resolve(user),
    login: () => Promise.resolve(user),
    logout: () => Promise.resolve(),
    listProjects: empty,
    listApprovals: empty,
    listPlans: empty,
    listRuns: empty,
    listFindings: empty,
    listAnalyses: empty,
    listSources: empty,
    listMembers: empty,
    listSessions: empty,
    listAuthorizations: empty,
    listFindingGroups: empty,
    listRunBatches: empty,
    listRunEvents: empty,
    listRunResults: empty,
    listBreakGlass: empty,
    getAlertThresholdLimits: empty,
    listUsers: empty,
    getEffectivePolicy: () => Promise.resolve({ approval_required_risk_levels: ['high'], allowed_risk_levels: ['low', 'medium', 'high'], high_risk_approver_roles: ['admin'], production_testing: { allowed: false }, risk_approvers: {}, risk_definitions: { low: 'Safe reads' } }),
    getProjectPolicies: () => Promise.resolve({ items: {}, effective: {} }),
    getGlobalPolicies: () => Promise.resolve({}),
    ...over,
  }
}

export const signedOutApi = (over = {}) => fakeApi({ me: () => Promise.reject(new Error('no session')), ...over })

export function renderApp(api, path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App api={api} />
    </MemoryRouter>,
  )
}
