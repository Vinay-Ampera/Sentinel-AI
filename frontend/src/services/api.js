// Shared API client. All backend calls go through here (no ad-hoc fetch in components).
// Role checks in the UI are usability only: the backend decides every action.

const BASE = import.meta.env.VITE_API_BASE_URL || '/api/v1'
const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

let csrfToken = null

export class ApiError extends Error {
  constructor(status, code, message, details = []) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

async function request(method, path, body) {
  const headers = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (UNSAFE.has(method) && csrfToken) headers['X-CSRF-Token'] = csrfToken
  let response
  try {
    response = await fetch(`${BASE}${path}`, {
      method,
      headers,
      credentials: 'include',
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'network_error', 'Could not reach the server')
  }
  if (response.status === 204) return null
  let data = null
  try {
    data = await response.json()
  } catch {
    // fall through: a non-JSON body is treated as an error below
  }
  if (!response.ok) {
    const e = data && data.error
    throw new ApiError(
      response.status,
      (e && e.code) || 'error',
      (e && e.message) || `Request failed (${response.status})`,
      (e && e.details) || [],
    )
  }
  return data
}

function bad(what) {
  return new ApiError(0, 'bad_response', `Unexpected response from the server (${what})`)
}

// Validate the shapes the UI depends on, at the boundary.
export function checkPlan(plan) {
  const ok =
    plan &&
    typeof plan.id === 'string' &&
    typeof plan.status === 'string' &&
    typeof plan.risk_level === 'string' &&
    Array.isArray(plan.tests) &&
    plan.tests.every((t) => t && typeof t.id === 'string' && typeof t.status === 'string')
  if (!ok) throw bad('plan')
  return plan
}

function checkItems(data, what) {
  if (!data || !Array.isArray(data.items)) throw bad(what)
  return data.items
}

export const api = {
  setCsrfToken(token) {
    csrfToken = token
  },
  async login(email, password) {
    const data = await request('POST', '/auth/login', { email, password })
    if (!data || !data.user || typeof data.csrf_token !== 'string') throw bad('login')
    csrfToken = data.csrf_token
    return data.user
  },
  async me() {
    const data = await request('GET', '/auth/me')
    if (!data || !data.user || typeof data.csrf_token !== 'string') throw bad('me')
    csrfToken = data.csrf_token
    return data.user
  },
  async logout() {
    await request('POST', '/auth/logout')
    csrfToken = null
  },
  async listProjects() {
    return checkItems(await request('GET', '/projects'), 'projects')
  },
  async listPlans(projectId) {
    return checkItems(await request('GET', `/projects/${projectId}/test-plans`), 'plans')
  },
  async createPlan(projectId, body) {
    return checkPlan(await request('POST', `/projects/${projectId}/test-plans`, body))
  },
  async getPlan(planId) {
    return checkPlan(await request('GET', `/test-plans/${planId}`))
  },
  async updatePlan(planId, body) {
    return checkPlan(await request('PATCH', `/test-plans/${planId}`, body))
  },
  async submitPlan(planId) {
    return checkPlan(await request('POST', `/test-plans/${planId}/submit`))
  },
  async listApprovals(status = 'pending') {
    return checkItems(await request('GET', `/approvals?status=${encodeURIComponent(status)}`), 'approvals')
  },
  async decideApproval(approvalId, decision, reason) {
    return request('POST', `/approvals/${approvalId}/decision`, { decision, reason })
  },
}
