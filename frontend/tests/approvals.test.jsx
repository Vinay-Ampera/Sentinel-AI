import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../src/services/api.js'
import { fakeApi, renderApp } from './helpers.jsx'

const approval = (over) => ({
  id: 'a1',
  project_id: 'p1',
  kind: 'authorization',
  plan_id: null,
  authorization_id: 'auth1',
  risk_level: 'high',
  decision: 'pending',
  requested_by: 'u2',
  decided_by: null,
  reason: null,
  created_at: '2026-10-20T10:00:00Z',
  decided_at: null,
  ...over,
})
const authorization = {
  id: 'auth1',
  environment: 'staging',
  scope: { paths: ['/api'], methods: ['GET'] },
  allowed_risk: ['low', 'high'],
  valid_until: '2026-11-01T00:00:00Z',
  justification: 'Weekly regression of staging API',
}
const project = { id: 'p1', name: 'Payments API', status: 'active', application_type: 'rest_api' }

const setup = (over = {}) =>
  fakeApi({
    listProjects: () => Promise.resolve([project]),
    listApprovals: vi.fn().mockResolvedValue([approval({}), approval({ id: 'a2', kind: 'plan', plan_id: 'plan9', authorization_id: null, risk_level: 'low' })]),
    listAuthorizations: () => Promise.resolve([authorization]),
    decideApproval: vi.fn().mockResolvedValue({}),
    ...over,
  })

describe('approvals workflow', () => {
  it('lists requests with project names; plans link to their review page, authorizations offer Decide', async () => {
    renderApp(setup(), '/approvals')
    expect(await screen.findByText('Target authorization')).toBeTruthy()
    expect(screen.getAllByText('Payments API').length).toBe(2)
    expect(screen.getByRole('link', { name: 'Review plan' }).getAttribute('href')).toBe('/projects/p1/plans/plan9')
    expect(screen.getByRole('button', { name: 'Decide' })).toBeTruthy()
  })

  it('shows what is being authorised and requires a 10-character reason to approve high risk', async () => {
    const api = setup()
    renderApp(api, '/approvals')
    fireEvent.click(await screen.findByRole('button', { name: 'Decide' }))
    const dialog = await screen.findByRole('dialog', { name: 'Target authorization request' })
    expect(await within(dialog).findByText('staging')).toBeTruthy()
    expect(within(dialog).getByText('Weekly regression of staging API')).toBeTruthy()

    const approve = within(dialog).getByRole('button', { name: 'Approve' })
    expect(approve.disabled).toBe(true)
    fireEvent.change(within(dialog).getByLabelText(/Reason/), { target: { value: 'too short' } })
    expect(approve.disabled).toBe(true)
    fireEvent.change(within(dialog).getByLabelText(/Reason/), { target: { value: 'Reviewed scope and window' } })
    expect(approve.disabled).toBe(false)
    fireEvent.click(approve)
    await waitFor(() => expect(api.decideApproval).toHaveBeenCalledWith('a1', 'approved', 'Reviewed scope and window'))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(api.listApprovals.mock.calls.length).toBeGreaterThan(1) // list reloaded after the decision
  })

  it('lets a reviewer reject without a reason', async () => {
    const api = setup()
    renderApp(api, '/approvals')
    fireEvent.click(await screen.findByRole('button', { name: 'Decide' }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Reject' }))
    await waitFor(() => expect(api.decideApproval).toHaveBeenCalledWith('a1', 'rejected', null))
  })

  it("shows the server's refusal in the dialog and keeps it open", async () => {
    const api = setup({ decideApproval: vi.fn().mockRejectedValue(new ApiError(403, 'forbidden', 'You cannot approve a request you made')) })
    renderApp(api, '/approvals')
    fireEvent.click(await screen.findByRole('button', { name: 'Decide' }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText(/Reason/), { target: { value: 'Reviewed scope and window' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Approve' }))
    expect((await within(dialog).findByRole('alert')).textContent).toMatch(/You cannot approve a request you made/)
    expect(screen.getByRole('dialog')).toBeTruthy()
  })

  it('says so when there is nothing to decide', async () => {
    renderApp(setup({ listApprovals: () => Promise.resolve([]) }), '/approvals')
    expect(await screen.findByText('Nothing is waiting for your decision')).toBeTruthy()
  })
})
