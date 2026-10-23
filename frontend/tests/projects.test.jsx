import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../src/services/api.js'
import { fakeApi, renderApp } from './helpers.jsx'

const project = { id: 'p9', name: 'Shop', description: null, status: 'active', application_type: 'web_app', your_access: 'manage', updated_at: '2026-10-20T10:00:00Z', created_at: '2026-10-20T10:00:00Z' }

describe('projects', () => {
  it('creates a project after validating required fields, then opens it', async () => {
    const api = fakeApi({ createProject: vi.fn().mockResolvedValue(project), getProject: () => Promise.resolve(project) })
    renderApp(api, '/projects')
    expect(await screen.findByText('No projects yet')).toBeTruthy()
    fireEvent.click(screen.getAllByRole('button', { name: /New project|Create your first project/ })[0])
    const dialog = await screen.findByRole('dialog', { name: 'New project' })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Create project' }))
    expect(await within(dialog).findByText('Enter a project name.')).toBeTruthy()
    expect(api.createProject).not.toHaveBeenCalled()

    fireEvent.change(within(dialog).getByLabelText(/Name/), { target: { value: 'Shop' } })
    fireEvent.change(within(dialog).getByLabelText(/Application type/), { target: { value: 'web_app' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Create project' }))
    await waitFor(() => expect(api.createProject).toHaveBeenCalledWith({ name: 'Shop', description: null, application_type: 'web_app' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Shop' })).toBeTruthy()
  })

  it('shows the server validation message in the dialog', async () => {
    const api = fakeApi({ createProject: vi.fn().mockRejectedValue(new ApiError(422, 'validation_failed', 'Project name already used')) })
    renderApp(api, '/projects')
    fireEvent.click((await screen.findAllByRole('button', { name: /New project|Create your first project/ }))[0])
    const dialog = await screen.findByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText(/Name/), { target: { value: 'Shop' } })
    fireEvent.change(within(dialog).getByLabelText(/Application type/), { target: { value: 'web_app' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Create project' }))
    expect((await within(dialog).findByRole('alert')).textContent).toMatch(/Project name already used/)
  })

  it('shows a project overview built from real calls, and says "none yet" where there is nothing', async () => {
    const api = fakeApi({
      getProject: () => Promise.resolve(project),
      listPlans: () => Promise.resolve([{ id: 'pl1', version: 2, status: 'draft', risk_level: 'low', created_at: '2026-10-21T10:00:00Z' }]),
    })
    renderApp(api, '/projects/p9')
    expect(await screen.findByRole('heading', { level: 1, name: 'Shop' })).toBeTruthy()
    expect(await screen.findByText(/Latest: version 2/)).toBeTruthy()
    expect(await screen.findByText('No runs yet')).toBeTruthy()
    expect(screen.getByText(/does not mean it was scanned and found clean/)).toBeTruthy()
  })

  it('explains a permission refusal in place instead of a generic error', async () => {
    const api = fakeApi({ getProject: () => Promise.resolve(project), listMembers: () => Promise.reject(new ApiError(403, 'forbidden', 'no')) })
    renderApp(api, '/projects/p9/setup')
    expect(await screen.findByText(/do not have access to this project's members/)).toBeTruthy()
  })
})
