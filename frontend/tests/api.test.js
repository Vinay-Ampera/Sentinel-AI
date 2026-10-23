import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api } from '../src/services/api.js'

const json = (status, body) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})
afterEach(() => {
  vi.unstubAllGlobals()
  api.setCsrfToken(null)
})

describe('api client', () => {
  it('sends credentials, and the CSRF token only on state-changing requests', async () => {
    fetch.mockImplementation(() => json(200, { user: { id: 'u', role: 'developer' }, csrf_token: 'tok' }))
    await api.login('a@example.com', 'pw')
    fetch.mockImplementation(() => json(200, { items: [] }))
    await api.listProjects()
    expect(fetch.mock.calls[1][1].headers['X-CSRF-Token']).toBeUndefined()
    expect(fetch.mock.calls[1][1].credentials).toBe('include')
    fetch.mockImplementation(() => json(200, { id: 'p', status: 'approved', risk_level: 'low', tests: [] }))
    await api.submitPlan('p')
    expect(fetch.mock.calls[2][1].headers['X-CSRF-Token']).toBe('tok')
    expect(fetch.mock.calls[2][0]).toBe('/api/v1/test-plans/p/submit')
  })

  it('turns the error envelope into an ApiError', async () => {
    fetch.mockImplementation(() => json(403, { error: { code: 'policy_blocked', message: 'Production testing is blocked by policy', request_id: 'r' } }))
    await expect(api.getPlan('x')).rejects.toMatchObject({ status: 403, code: 'policy_blocked', message: 'Production testing is blocked by policy' })
  })

  it('reports an unreachable server and a malformed response', async () => {
    fetch.mockRejectedValueOnce(new TypeError('failed'))
    await expect(api.getPlan('x')).rejects.toMatchObject({ code: 'network_error' })
    fetch.mockImplementation(() => json(200, { id: 'p' }))
    await expect(api.getPlan('x')).rejects.toBeInstanceOf(ApiError)
    fetch.mockImplementation(() => json(200, { id: 'p' }))
    await expect(api.getPlan('x')).rejects.toMatchObject({ code: 'bad_response' })
  })

  it('starts a run with an idempotency key and the CSRF token', async () => {
    fetch.mockImplementation(() => json(200, { user: { id: 'u', role: 'developer' }, csrf_token: 'tok' }))
    await api.login('a@example.com', 'pw')
    fetch.mockImplementation(() => json(202, { id: 'r', status: 'queued', plan_id: 'p', progress: { tests_total: 2, tests_finished: 0 } }))
    const run = await api.createRun('proj', 'p', 'key-12345678')
    expect(run.status).toBe('queued')
    const [url, init] = fetch.mock.calls[1]
    expect(url).toBe('/api/v1/projects/proj/test-runs')
    expect(init.headers['Idempotency-Key']).toBe('key-12345678')
    expect(init.headers['X-CSRF-Token']).toBe('tok')
    expect(JSON.parse(init.body)).toEqual({ plan_id: 'p' })
  })

  it('rejects malformed run and result responses at the boundary', async () => {
    fetch.mockImplementation(() => json(200, { id: 'r' }))
    await expect(api.getRun('r')).rejects.toMatchObject({ code: 'bad_response' })
    fetch.mockImplementation(() => json(200, [{ id: 'x' }]))
    await expect(api.listRunResults('r')).rejects.toMatchObject({ code: 'bad_response' })
    fetch.mockImplementation(() => json(200, { id: 'x', status: 'passed', planned_test_id: 't' }))
    await expect(api.getRunResult('r', 'x')).rejects.toMatchObject({ code: 'bad_response' }) // no cases/evidence
  })

  it('reads evidence as text, shortened, and reports errors', async () => {
    fetch.mockImplementation(() => Promise.resolve(new Response('x'.repeat(300000), { status: 200 })))
    const ev = await api.getEvidenceText('a1')
    expect(ev.text.length).toBe(200000)
    expect(ev.truncated).toBe(true)
    expect(fetch.mock.calls[0][0]).toBe('/api/v1/artifacts/a1/content')
    expect(fetch.mock.calls[0][1].credentials).toBe('include')
    fetch.mockImplementation(() => json(404, { error: { code: 'not_found', message: 'Evidence not found' } }))
    await expect(api.getEvidenceText('a2')).rejects.toMatchObject({ status: 404, message: 'Evidence not found' })
  })
})

describe('findings client', () => {
  const f = { id: 'f', title: 't', severity: 'high', confidence: 'low', status: 'new', verification_state: 'unverified' }
  it('lists with filters and rejects malformed data', async () => {
    fetch.mockImplementation(() => json(200, [f]))
    await api.listFindings('p', { status: 'new', severity: '' })
    expect(fetch.mock.calls[0][0]).toBe('/api/v1/projects/p/findings?status=new')
    fetch.mockImplementation(() => json(200, [{ id: 'f' }]))
    await expect(api.listFindings('p')).rejects.toMatchObject({ code: 'bad_response' })
    fetch.mockImplementation(() => json(200, { items: [] }))
    await expect(api.listFindings('p')).rejects.toMatchObject({ code: 'bad_response' })
  })

  it('posts status and verification with the CSRF token and requires a full detail back', async () => {
    api.setCsrfToken('tok')
    const detail = { ...f, events: [], evidence: [], attempts: [] }
    fetch.mockImplementation(() => json(200, detail))
    await api.setFindingStatus('f', 'triaged', '')
    expect(fetch.mock.calls[0][0]).toBe('/api/v1/findings/f/status')
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ status: 'triaged', note: null })
    expect(fetch.mock.calls[0][1].headers['X-CSRF-Token']).toBe('tok')
    await api.setFindingVerification('f', 'likely', 'Reproduced by hand')
    expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ state: 'likely', note: 'Reproduced by hand' })
    fetch.mockImplementation(() => json(200, f))
    await expect(api.getFinding('f')).rejects.toMatchObject({ code: 'bad_response' })
  })
})
