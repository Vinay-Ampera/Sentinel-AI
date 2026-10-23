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
})
