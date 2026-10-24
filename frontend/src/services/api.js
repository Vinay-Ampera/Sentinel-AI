// Shared API client. All backend calls go through here (no ad-hoc fetch in components).
// Role checks in the UI are usability only: the backend decides every action.

const BASE = import.meta.env.VITE_API_BASE_URL || '/api/v1'
const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

let csrfToken = null
let unauthorizedHandler = null

// Called when an authenticated request comes back 401 (the session ended). Sign-in and the
// session probe are excluded: a 401 there is a normal answer, not an expiry.
export function setUnauthorizedHandler(fn) {
  unauthorizedHandler = fn
}
const NOT_AN_EXPIRY = new Set(['/auth/login', '/auth/me'])

export class ApiError extends Error {
  constructor(status, code, message, details = []) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

async function request(method, path, body, extraHeaders = {}, raw = false) {
  const headers = { Accept: 'application/json', ...extraHeaders }
  if (body !== undefined && !raw) headers['Content-Type'] = 'application/json'
  if (UNSAFE.has(method) && csrfToken) headers['X-CSRF-Token'] = csrfToken
  let response
  try {
    response = await fetch(`${BASE}${path}`, {
      method,
      headers,
      credentials: 'include',
      body: body === undefined ? undefined : raw ? body : JSON.stringify(body),
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
    if (response.status === 401 && unauthorizedHandler && !NOT_AN_EXPIRY.has(path)) unauthorizedHandler()
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

function checkProject(p) {
  const ok = p && typeof p.id === 'string' && typeof p.name === 'string' && typeof p.status === 'string' && typeof p.application_type === 'string'
  if (!ok) throw bad('project')
  return p
}

function checkSnapshot(a) {
  const ok = a && typeof a.id === 'string' && typeof a.status === 'string' && a.result && typeof a.result === 'object'
  if (!ok) throw bad('analysis')
  return a
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

function checkFinding(f) {
  const ok =
    f &&
    typeof f.id === 'string' &&
    typeof f.title === 'string' &&
    typeof f.severity === 'string' &&
    typeof f.confidence === 'string' &&
    typeof f.status === 'string' &&
    typeof f.verification_state === 'string'
  if (!ok) throw bad('finding')
  return f
}

function checkFindingDetail(f) {
  checkFinding(f)
  if (!Array.isArray(f.events) || !Array.isArray(f.evidence) || !Array.isArray(f.attempts)) throw bad('finding detail')
  if (f.related !== undefined && !Array.isArray(f.related)) throw bad('finding detail')
  return f
}

function checkAgentRun(r) {
  const ok =
    r &&
    typeof r.id === 'string' &&
    typeof r.workflow === 'string' &&
    typeof r.status === 'string' &&
    (r.result === null || r.result === undefined || typeof r.result === 'object') &&
    (r.steps === null || r.steps === undefined || (Array.isArray(r.steps) && r.steps.every((s) => s && typeof s.seq === 'number' && typeof s.node === 'string')))
  if (!ok) throw bad('agent run')
  return r
}

function checkProposal(p) {
  const ok =
    p &&
    typeof p.id === 'string' &&
    typeof p.status === 'string' &&
    typeof p.title === 'string' &&
    typeof p.code === 'string' &&
    Array.isArray(p.risk_flags) &&
    Array.isArray(p.overlap) &&
    Array.isArray(p.evidence_ids)
  if (!ok) throw bad('regression proposal')
  return p
}

const isObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v)

function checkAlert(a) {
  const ok =
    a &&
    typeof a.id === 'string' &&
    typeof a.rule === 'string' &&
    typeof a.title === 'string' &&
    typeof a.severity === 'string' &&
    typeof a.status === 'string' &&
    typeof a.next_action === 'string' &&
    isObject(a.measured) &&
    isObject(a.evidence)
  if (!ok) throw bad('alert')
  return a
}

function checkAlertDetail(a) {
  checkAlert(a)
  if (!Array.isArray(a.history) || !Array.isArray(a.proposal_ids) || !isObject(a.telemetry)) throw bad('alert detail')
  return a
}

function checkTelemetry(t) {
  const ok = isObject(t) && typeof t.has_events === 'boolean' && typeof t.ingest_enabled === 'boolean' && Array.isArray(t.limits) && isObject(t.dropped_last_24h)
  if (!ok) throw bad('telemetry status')
  return t
}

function checkGroup(g) {
  const ok = g && typeof g.id === 'string' && typeof g.message === 'string' && typeof g.total_count === 'number' && typeof g.level_class === 'string'
  if (!ok) throw bad('event group')
  return g
}

function checkIngestKey(k) {
  const ok = k && typeof k.id === 'string' && typeof k.key_id === 'string' && typeof k.label === 'string' && typeof k.status === 'string'
  if (!ok) throw bad('ingest key')
  return k
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
  async listProjects(includeArchived = false) {
    return checkItems(await request('GET', `/projects${includeArchived ? '?include_archived=true' : ''}`), 'projects').map(checkProject)
  },
  async createProject(body) {
    return checkProject(await request('POST', '/projects', body))
  },
  async getProject(projectId) {
    return checkProject(await request('GET', `/projects/${projectId}`))
  },
  async archiveProject(projectId) {
    return checkProject(await request('POST', `/projects/${projectId}/archive`))
  },
  async listMembers(projectId) {
    return checkItems(await request('GET', `/projects/${projectId}/members`), 'members')
  },
  async setMember(projectId, userId, accessLevel) {
    await request('PUT', `/projects/${projectId}/members/${userId}`, { access_level: accessLevel })
  },
  async removeMember(projectId, userId) {
    await request('DELETE', `/projects/${projectId}/members/${userId}`)
  },
  async listUsers(q = '') {
    return checkItems(await request('GET', `/users${q ? `?q=${encodeURIComponent(q)}` : ''}`), 'users')
  },
  async listSources(projectId) {
    return checkItems(await request('GET', `/projects/${projectId}/sources`), 'sources')
  },
  async addUrlSource(projectId, body) {
    return request('POST', `/projects/${projectId}/sources`, body)
  },
  // The ZIP is sent as the raw request body (application/zip), as the backend expects. It is
  // never read or unpacked in the browser.
  async uploadZipSource(projectId, name, file) {
    return request('POST', `/projects/${projectId}/sources/zip?name=${encodeURIComponent(name)}`, file, { 'Content-Type': 'application/zip' }, true)
  },
  async removeSource(projectId, sourceId) {
    await request('DELETE', `/projects/${projectId}/sources/${sourceId}`)
  },
  async listAnalyses(projectId) {
    return checkItems(await request('GET', `/projects/${projectId}/analyses`), 'analyses').map(checkSnapshot)
  },
  async getAnalysis(analysisId) {
    return checkSnapshot(await request('GET', `/analyses/${analysisId}`))
  },
  async runAnalysis(projectId, sourceId) {
    return checkSnapshot(await request('POST', `/projects/${projectId}/analyses`, { source_id: sourceId }))
  },
  async listAuthorizations(projectId) {
    return checkItems(await request('GET', `/projects/${projectId}/authorizations`), 'authorizations')
  },
  async listFindingGroups(projectId) {
    const data = await request('GET', `/projects/${projectId}/finding-groups`)
    if (!Array.isArray(data)) throw bad('finding groups')
    return data
  },
  async getEffectivePolicy(projectId) {
    return request('GET', `/projects/${projectId}/policy`)
  },
  async getProjectPolicies(projectId) {
    const data = await request('GET', `/projects/${projectId}/policies`)
    if (!data || typeof data.items !== 'object') throw bad('policies')
    return data
  },
  async setProjectPolicy(projectId, key, value) {
    return request('PUT', `/projects/${projectId}/policies/${key}`, { value })
  },
  async getGlobalPolicies() {
    const data = await request('GET', '/admin/policies')
    if (!data || typeof data.items !== 'object') throw bad('policies')
    return data.items
  },
  async getAlertThresholdLimits() {
    const data = await request('GET', '/admin/alert-threshold-limits')
    if (!data || !Array.isArray(data.items) || !data.items.every((i) => typeof i.name === 'string' && typeof i.min === 'number' && typeof i.max === 'number' && typeof i.default === 'number')) throw bad('alert threshold limits')
    return data.items
  },
  async setGlobalPolicy(key, value) {
    return request('PUT', `/admin/policies/${key}`, { value })
  },
  async requestAuthorization(projectId, sourceId, body) {
    return request('POST', `/projects/${projectId}/sources/${sourceId}/authorizations`, body)
  },
  async revokeAuthorization(projectId, authorizationId) {
    return request('POST', `/projects/${projectId}/authorizations/${authorizationId}/revoke`)
  },
  async listBreakGlass(projectId) {
    return checkItems(await request('GET', `/projects/${projectId}/break-glass`), 'break-glass')
  },
  async grantBreakGlass(projectId, justification, minutes) {
    return request('POST', `/projects/${projectId}/break-glass`, { justification, minutes })
  },
  async revokeBreakGlass(projectId, grantId) {
    return request('POST', `/projects/${projectId}/break-glass/${grantId}/revoke`)
  },
  async createUser(body) {
    return request('POST', '/admin/users', body)
  },
  async updateUser(userId, body) {
    return request('PATCH', `/admin/users/${userId}`, body)
  },
  async changePassword(current, next) {
    return request('POST', '/auth/password', { current, new: next })
  },
  async listSessions() {
    return checkItems(await request('GET', '/auth/sessions'), 'sessions')
  },
  async revokeSession(sessionId) {
    await request('DELETE', `/auth/sessions/${sessionId}`)
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
  async listRunBatches(runId) {
    const data = await request('GET', `/test-runs/${runId}/batches`)
    if (!Array.isArray(data)) throw bad('batches')
    return data
  },
  async listRunEvents(runId, after = 0) {
    const data = await request('GET', `/test-runs/${runId}/events?after=${after}`)
    if (!Array.isArray(data)) throw bad('events')
    return data
  },
  // Same-origin link to download an evidence file (the server sends it as an attachment).
  evidenceUrl(artifactId) {
    return `${BASE}/artifacts/${artifactId}/content`
  },
  async listFindings(projectId, filters = {}) {
    const q = new URLSearchParams(Object.entries(filters).filter(([, v]) => v)).toString()
    const data = await request('GET', `/projects/${projectId}/findings${q ? `?${q}` : ''}`)
    if (!Array.isArray(data)) throw bad('findings')
    return data.map(checkFinding)
  },
  // Assistant (Stage 11). A run's text fields come from a model and are only ever shown as text.
  async listAgentRuns(projectId) {
    return checkItems(await request('GET', `/projects/${projectId}/agent-runs`), 'agent runs').map(checkAgentRun)
  },
  async getAgentRun(projectId, runId) {
    return checkAgentRun(await request('GET', `/projects/${projectId}/agent-runs/${runId}`))
  },
  async createAgentRun(projectId, body) {
    return checkAgentRun(await request('POST', `/projects/${projectId}/agent-runs`, body))
  },
  async listRegressionProposals(projectId) {
    return checkItems(await request('GET', `/projects/${projectId}/regression-proposals`), 'regression proposals').map(checkProposal)
  },
  async getTelemetryStatus(projectId) {
    return checkTelemetry(await request('GET', `/projects/${projectId}/telemetry-status`))
  },
  async listAlerts(projectId, { status, severity, rule } = {}) {
    const query = new URLSearchParams()
    if (status) query.set('status', status)
    if (severity) query.set('severity', severity)
    if (rule) query.set('rule', rule)
    const qs = query.toString()
    return checkItems(await request('GET', `/projects/${projectId}/alerts${qs ? `?${qs}` : ''}`), 'alerts').map(checkAlert)
  },
  async getAlert(projectId, alertId) {
    return checkAlertDetail(await request('GET', `/projects/${projectId}/alerts/${alertId}`))
  },
  async acknowledgeAlert(projectId, alertId, note) {
    return checkAlert(await request('POST', `/projects/${projectId}/alerts/${alertId}/acknowledge`, { note: note || null }))
  },
  async resolveAlert(projectId, alertId, note) {
    return checkAlert(await request('POST', `/projects/${projectId}/alerts/${alertId}/resolve`, { note: note || null }))
  },
  async getTrace(projectId, traceId) {
    const t = await request('GET', `/projects/${projectId}/traces/${traceId}`)
    if (!isObject(t) || !Array.isArray(t.runs) || !Array.isArray(t.assistant_runs) || !Array.isArray(t.events) || !Array.isArray(t.limits)) throw bad('trace')
    return t
  },
  async listEventGroups(projectId) {
    return checkItems(await request('GET', `/projects/${projectId}/event-groups`), 'event groups').map(checkGroup)
  },
  async getEventGroup(projectId, groupId) {
    const g = checkGroup(await request('GET', `/projects/${projectId}/event-groups/${groupId}`))
    if (!Array.isArray(g.samples) || !Array.isArray(g.limits)) throw bad('event group')
    return g
  },
  async listIngestKeys(projectId) {
    return checkItems(await request('GET', `/projects/${projectId}/ingest-keys`), 'ingest keys').map(checkIngestKey)
  },
  async createIngestKey(projectId, label, expiresInDays) {
    const body = { label }
    if (expiresInDays) body.expires_in_days = expiresInDays
    const k = checkIngestKey(await request('POST', `/projects/${projectId}/ingest-keys`, body))
    if (typeof k.key !== 'string') throw bad('ingest key')
    return k
  },
  async revokeIngestKey(projectId, keyId) {
    return checkIngestKey(await request('DELETE', `/projects/${projectId}/ingest-keys/${keyId}`))
  },
  async decideRegressionProposal(projectId, proposalId, decision, note) {
    return checkProposal(await request('POST', `/projects/${projectId}/regression-proposals/${proposalId}/decision`, { decision, note: note || null }))
  },
  async getFinding(findingId) {
    return checkFindingDetail(await request('GET', `/findings/${findingId}`))
  },
  async setFindingStatus(findingId, status, note) {
    return checkFindingDetail(await request('POST', `/findings/${findingId}/status`, { status, note: note || null }))
  },
  async setFindingVerification(findingId, state, note) {
    return checkFindingDetail(await request('POST', `/findings/${findingId}/verification`, { state, note }))
  },
  getEvidenceText(artifactId) {
    return requestText(`/artifacts/${artifactId}/content`)
  },
}
