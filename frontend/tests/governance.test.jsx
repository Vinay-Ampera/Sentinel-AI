import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../src/services/api.js'
import { admin, fakeApi, project, renderApp, user } from './helpers.jsx'

const source = { id: 's1', source_type: 'remote_url', name: 'Staging API', is_active: true, target_url: 'https://staging.example.com', environment: 'staging' }
const authorization = { id: 'auth1', source_id: 's1', environment: 'staging', scope: { paths: ['/api'], methods: ['GET'] }, allowed_risk: ['low'], status: 'approved', valid_until: '2026-11-01T00:00:00Z', in_effect: true }

const api = (over = {}) =>
  fakeApi({
    me: () => Promise.resolve(user),
    getProject: () => Promise.resolve(project),
    listSources: () => Promise.resolve([source]),
    listAuthorizations: vi.fn().mockResolvedValue([authorization]),
    requestAuthorization: vi.fn().mockResolvedValue({}),
    revokeAuthorization: vi.fn().mockResolvedValue({}),
    ...over,
  })

describe('project governance', () => {
  it('requests a target authorization with a scope and a window, after checking the justification', async () => {
    const a = api()
    renderApp(a, '/projects/p1/governance')
    fireEvent.click(await screen.findByRole('button', { name: 'Request authorization' }))
    const dialog = await screen.findByRole('dialog', { name: 'Request target authorization' })
    fireEvent.change(within(dialog).getByLabelText(/^Target/), { target: { value: 's1' } })
    fireEvent.change(within(dialog).getByLabelText(/Why is this needed/), { target: { value: 'short' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Request authorization' }))
    expect(await within(dialog).findByText('Write at least 10 characters.')).toBeTruthy()
    expect(a.requestAuthorization).not.toHaveBeenCalled()

    fireEvent.change(within(dialog).getByLabelText(/Why is this needed/), { target: { value: 'Weekly regression of staging' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Request authorization' }))
    await waitFor(() => expect(a.requestAuthorization).toHaveBeenCalled())
    const [pid, sid, body] = a.requestAuthorization.mock.calls[0]
    expect([pid, sid]).toEqual(['p1', 's1'])
    expect(body).toMatchObject({ environment: 'staging', paths: ['/'], methods: ['GET', 'HEAD', 'OPTIONS'], allowed_risk: ['low'], justification: 'Weekly regression of staging' })
    expect(new Date(body.valid_until).getTime()).toBeGreaterThan(Date.now())
  })

  it('revokes an authorization only after confirmation', async () => {
    const a = api()
    renderApp(a, '/projects/p1/governance')
    fireEvent.click(await screen.findByRole('button', { name: /Revoke authorization for Staging API/ }))
    expect(a.revokeAuthorization).not.toHaveBeenCalled()
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Revoke' }))
    await waitFor(() => expect(a.revokeAuthorization).toHaveBeenCalledWith('p1', 'auth1'))
  })

  it('saves a tightened policy and shows the server refusal for an invalid one', async () => {
    const a = api({ setProjectPolicy: vi.fn().mockRejectedValueOnce(new ApiError(403, 'policy_blocked', 'A project cannot loosen organization policy')).mockResolvedValue({}) })
    renderApp(a, '/projects/p1/governance')
    const group = (await screen.findByText('Risk levels that need approval')).closest('fieldset')
    fireEvent.click(within(group).getByLabelText('medium'))
    fireEvent.click(within(group).getByRole('button', { name: 'Save' }))
    expect((await within(group).findByRole('alert')).textContent).toMatch(/cannot loosen organization policy/)
    fireEvent.click(within(group).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(a.setProjectPolicy).toHaveBeenLastCalledWith('p1', 'approval_required_risk_levels', ['medium', 'high']))
  })

  it('offers emergency access only to a super admin', async () => {
    renderApp(api({ me: () => Promise.resolve({ ...user, role: 'super_admin' }) }), '/projects/p1/governance')
    expect(await screen.findByRole('heading', { name: 'Grant emergency access' })).toBeTruthy()
  })

  it('does not offer emergency access to others', async () => {
    renderApp(api(), '/projects/p1/governance')
    await screen.findByText('No emergency access has been used on this project')
    expect(screen.queryByRole('heading', { name: 'Grant emergency access' })).toBeNull()
  })
})

describe('administration and role-aware navigation', () => {
  it('shows the Admin link only to admins and keeps others out of the page', async () => {
    const { unmount } = renderApp(fakeApi({ me: () => Promise.resolve(user) }), '/admin')
    expect(await screen.findByText(/do not have access to administration/)).toBeTruthy()
    expect(screen.queryByRole('link', { name: 'Admin' })).toBeNull() // neither in the navbar nor the footer
    unmount()
    renderApp(fakeApi({ me: () => Promise.resolve(admin) }), '/admin')
    expect(await screen.findByRole('heading', { level: 1, name: 'Administration' })).toBeTruthy()
    expect(within(screen.getByRole('navigation', { name: 'Primary' })).getByRole('link', { name: 'Admin' })).toBeTruthy()
  })

  it('creates a user with the required fields and shows the server refusal for a privileged role', async () => {
    const a = fakeApi({
      me: () => Promise.resolve(admin),
      createUser: vi.fn().mockRejectedValueOnce(new ApiError(403, 'forbidden', 'Only a super admin may create privileged accounts')).mockResolvedValue({}),
    })
    renderApp(a, '/admin')
    fireEvent.click(await screen.findByRole('button', { name: 'New user' }))
    const dialog = await screen.findByRole('dialog', { name: 'New user' })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Create user' }))
    expect(await within(dialog).findByText('Enter an email address.')).toBeTruthy()
    fireEvent.change(within(dialog).getByLabelText(/^Email/), { target: { value: 'new@example.com' } })
    fireEvent.change(within(dialog).getByLabelText(/Display name/), { target: { value: 'New Person' } })
    fireEvent.change(within(dialog).getByLabelText('Role'), { target: { value: 'super_admin' } })
    fireEvent.change(within(dialog).getByLabelText(/Initial password/), { target: { value: 'a-long-initial-password' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Create user' }))
    expect((await within(dialog).findByRole('alert')).textContent).toMatch(/Only a super admin/)
    fireEvent.change(within(dialog).getByLabelText('Role'), { target: { value: 'developer' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Create user' }))
    await waitFor(() => expect(a.createUser).toHaveBeenLastCalledWith({ email: 'new@example.com', display_name: 'New Person', role: 'developer', password: 'a-long-initial-password' }))
  })
})

describe('roadmap', () => {
  it('lists planned work with stage labels and no interactive controls inside the list', async () => {
    renderApp(fakeApi({ me: () => Promise.reject(new Error('no')) }), '/roadmap')
    expect(await screen.findByText('Nothing on this list is available yet')).toBeTruthy()
    const items = screen.getAllByRole('listitem').filter((li) => li.className === 'roadmap-item')
    expect(items.length).toBe(5)
    expect(items.every((li) => li.querySelector('button, a') === null)).toBe(true)
  })
})
