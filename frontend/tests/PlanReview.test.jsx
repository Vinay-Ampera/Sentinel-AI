import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import PlanReview from '../src/features/plans/PlanReview.jsx'
import { ApiError } from '../src/services/api.js'

afterEach(cleanup)

const test = (over) => ({
  id: 't1',
  ordinal: 1,
  name: 'Python unit tests (pytest)',
  category: 'functional',
  tool: 'pytest',
  origin: 'recommended',
  risk_level: 'low',
  requires_approval: false,
  status: 'planned',
  rationale: 'Python tests were detected (1 example file(s), e.g. tests/test_a.py).',
  target: { name: 'code', source_type: 'zip_upload' },
  prerequisites: ['Project dependencies installable in the sandbox'],
  expected_evidence: ['JUnit XML report'],
  parameters: {},
  script_artifact_id: null,
  ...over,
})

const plan = (over = {}) => ({
  id: 'p1',
  project_id: 'proj',
  version: 1,
  mode: 'automatic',
  status: 'draft',
  risk_level: 'low',
  summary: null,
  prompt: null,
  content_sha256: null,
  tests: [
    test({}),
    test({ id: 't2', name: 'HTTP smoke checks', tool: 'http_probe', status: 'deferred', rationale: 'Needs a running target: register a localhost URL.' }),
    test({ id: 't3', name: 'LLM probes', tool: 'llm_probe', status: 'skipped', rationale: 'Not applicable: ai_app only.' }),
  ],
  counts: { planned: 1, deferred: 1, skipped: 1 },
  approval: null,
  execution_available: false,
  notice: 'Planning only: no test runner is connected yet, so nothing has been executed.',
  ...over,
})

const fakeApi = (over = {}) => ({
  getPlan: vi.fn().mockResolvedValue(plan()),
  updatePlan: vi.fn(),
  submitPlan: vi.fn(),
  decideApproval: vi.fn(),
  ...over,
})

describe('PlanReview', () => {
  it('shows a loading state, then every check with its status and reason, without implying results', async () => {
    render(<PlanReview api={fakeApi()} planId="p1" user={{ id: 'u1', role: 'developer' }} />)
    expect(screen.getByRole('status').textContent).toMatch(/loading/i)
    expect(await screen.findByText(/nothing has been executed/)).toBeTruthy()
    expect(screen.getByRole('group', { name: 'Planned' })).toBeTruthy()
    expect(screen.getByRole('group', { name: 'Unavailable' })).toBeTruthy()
    expect(screen.getByRole('group', { name: 'Not applicable' })).toBeTruthy()
    expect(screen.getByText(/Needs a running target/)).toBeTruthy()
    expect(screen.getByText(/Not applicable: ai_app only/)).toBeTruthy()
    expect(document.body.textContent).not.toMatch(/passed|confirmed|vulnerab/i)
  })

  it('shows an error with a retry', async () => {
    const getPlan = vi.fn().mockRejectedValueOnce(new ApiError(404, 'not_found', 'Plan not found')).mockResolvedValue(plan())
    render(<PlanReview api={fakeApi({ getPlan })} planId="p1" user={null} />)
    expect((await screen.findByRole('alert')).textContent).toMatch(/Plan not found/)
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('group', { name: 'Planned' })).toBeTruthy()
  })

  it('shows an empty state for a plan without checks', async () => {
    render(<PlanReview api={fakeApi({ getPlan: vi.fn().mockResolvedValue(plan({ tests: [], counts: {} })) })} planId="p1" user={null} />)
    expect(await screen.findByText('This plan contains no checks.')).toBeTruthy()
  })

  it('lets a draft be edited and submitted, and shows the server message when refused', async () => {
    const api = fakeApi({
      updatePlan: vi.fn().mockResolvedValue(plan({ tests: [test({})], counts: { planned: 1 } })),
      submitPlan: vi.fn().mockRejectedValue(new ApiError(422, 'no_runnable_tests', 'The plan has no test that can run')),
    })
    render(<PlanReview api={api} planId="p1" user={{ id: 'u1', role: 'developer' }} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Remove HTTP smoke checks' }))
    await waitFor(() => expect(api.updatePlan).toHaveBeenCalledWith('p1', { remove_test_ids: ['t2'] }))
    await waitFor(() => expect(screen.queryByRole('group', { name: 'Unavailable' })).toBeNull())
    fireEvent.click(screen.getByRole('button', { name: 'Submit for approval' }))
    expect((await screen.findByRole('alert')).textContent).toMatch(/no test that can run/)
  })

  const pendingPlan = (requestedBy, canApprove = false) =>
    plan({
      viewer_can_approve: canApprove,
      status: 'pending_approval',
      risk_level: 'high',
      approval: { id: 'a1', decision: 'pending', risk_level: 'high', requested_by: requestedBy, reason: null },
    })

  it('offers approval only when the server says the viewer can approve (any role) and sends the typed reason', async () => {
    const api = fakeApi({ getPlan: vi.fn().mockResolvedValue(pendingPlan('u-dev', true)), decideApproval: vi.fn().mockResolvedValue({}) })
    render(<PlanReview api={api} planId="p1" user={{ id: 'u-mgr', role: 'developer' }} />)
    fireEvent.change(await screen.findByLabelText(/Reason/), { target: { value: 'Scope is the local dev server' } })
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
    await waitFor(() => expect(api.decideApproval).toHaveBeenCalledWith('a1', 'approved', 'Scope is the local dev server'))
  })

  it('does not offer Approve to developers or to the requester, who can only withdraw', async () => {
    const dev = render(<PlanReview api={fakeApi({ getPlan: vi.fn().mockResolvedValue(pendingPlan('u-other')) })} planId="p1" user={{ id: 'u-dev', role: 'developer' }} />)
    expect(await screen.findByText(/Waiting for the project/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull()
    dev.unmount()
    render(<PlanReview api={fakeApi({ getPlan: vi.fn().mockResolvedValue(pendingPlan('u-admin')) })} planId="p1" user={{ id: 'u-admin', role: 'admin' }} />)
    expect(await screen.findByRole('button', { name: 'Withdraw' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull()
  })

  it('shows the server refusal when a decision is denied', async () => {
    const api = fakeApi({
      getPlan: vi.fn().mockResolvedValue(pendingPlan('u-dev', true)),
      decideApproval: vi.fn().mockRejectedValue(new ApiError(403, 'forbidden', 'You cannot approve work you requested')),
    })
    render(<PlanReview api={api} planId="p1" user={{ id: 'u-admin', role: 'admin' }} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Reject' }))
    expect((await screen.findByRole('alert')).textContent).toMatch(/cannot approve work you requested/)
  })
})
