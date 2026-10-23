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

async function request(method, path, body, extraHeaders = {}) {
  const headers = { Accept: 'application/json', ...extraHeaders }
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

export function checkRun(run) {
  const ok =
    run &&
    typeof run.id === 'string' &&
    typeof run.status === 'string' &&
    typeof run.plan_id === 'string' &&
    (run.progress === null ||
      run.progress === undefined ||
      (typeof run.progress.tests_total === 'number' && typeof run.progress.tests_finished === 'number'))
  if (!ok) throw bad('run')
  return run
}

function checkResult(result) {
  const ok =
    result &&
    typeof result.id === 'string' &&
    typeof result.status === 'string' &&
    typeof result.planned_test_id === 'string'
  if (!ok) throw bad('result')
  return result
}

// Evidence is untrusted text from a sandbox: fetched as text, never rendered as HTML, and
// shortened for display (the full file stays downloadable).
const EVIDENCE_LIMIT = 200_000

async function requestText(path) {
  let response
  try {
    response = await fetch(`${BASE}${path}`, { credentials: 'include' })
  } catch {
    throw new ApiError(0, 'network_error', 'Could not reach the server')
  }
  if (!response.ok) {
    let e = null
    try {
      e = (await response.json()).error
    } catch {
      // not JSON
    }
    throw new ApiError(response.status, (e && e.code) || 'error', (e && e.message) || `Request failed (${response.status})`)
  }
  const text = await response.text()
  return { text: text.slice(0, EVIDENCE_LIMIT), truncated: text.length > EVIDENCE_LIMIT }
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
  async listRuns(projectId) {
    const data = await request('GET', `/projects/${projectId}/test-runs`)
    if (!Array.isArray(data)) throw bad('runs')
    return data.map(checkRun)
  },
  async createRun(projectId, planId, idempotencyKey) {
    return checkRun(
      await request('POST', `/projects/${projectId}/test-runs`, { plan_id: planId }, { 'Idempotency-Key': idempotencyKey }),
    )
  },
  async getRun(runId) {
    return checkRun(await request('GET', `/test-runs/${runId}`))
  },
  async cancelRun(runId) {
    return checkRun(await request('POST', `/test-runs/${runId}/cancel`))
  },
  async listRunResults(runId) {
    const data = await request('GET', `/test-runs/${runId}/results`)
    if (!Array.isArray(data)) throw bad('results')
    return data.map(checkResult)
  },
  async getRunResult(runId, resultId) {
    const data = checkResult(await request('GET', `/test-runs/${runId}/results/${resultId}`))
    if (!Array.isArray(data.cases) || !Array.isArray(data.evidence)) throw bad('result detail')
    return data
  },
  getEvidenceText(artifactId) {
    return requestText(`/artifacts/${artifactId}/content`)
  },
}
