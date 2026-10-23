import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/app/App.jsx'
import { safeNextPath } from '../src/lib/safeNext.js'
import { api as realApi } from '../src/services/api.js'
import { ApiError } from '../src/services/api.js'
import { fakeApi, renderApp, signedOutApi, user } from './helpers.jsx'

const signIn = (email = 'dana@example.com', password = 'a-long-password') => {
  fireEvent.change(screen.getByLabelText(/Email/), { target: { value: email } })
  fireEvent.change(screen.getByLabelText(/^Password/), { target: { value: password } })
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
}

describe('safeNextPath', () => {
  it.each([
    ['/projects/abc?tab=1', '/projects/abc?tab=1'],
    ['https://evil.example/x', '/projects'],
    ['//evil.example/x', '/projects'],
    ['/\\evil.example', '/projects'],
    ['javascript:alert(1)', '/projects'],
    ['/signin', '/projects'],
    [null, '/projects'],
    ['/a\nb', '/projects'],
  ])('%s -> %s', (input, expected) => {
    expect(safeNextPath(input)).toBe(expected)
  })
})

describe('sign-in and route protection', () => {
  it('sends a signed-out visitor to sign in, then back to the page they asked for', async () => {
    const api = signedOutApi({ login: vi.fn().mockResolvedValue(user), listApprovals: () => Promise.resolve([]) })
    renderApp(api, '/approvals')
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeTruthy()
    signIn()
    expect(api.login).toHaveBeenCalledWith('dana@example.com', 'a-long-password')
    expect(await screen.findByRole('heading', { level: 1, name: 'Approvals' })).toBeTruthy()
  })

  it('does not follow an off-site next target after sign-in', async () => {
    renderApp(signedOutApi(), '/signin?next=https%3A%2F%2Fevil.example')
    await screen.findByRole('heading', { name: 'Sign in' })
    signIn()
    expect(await screen.findByRole('heading', { level: 1, name: 'Projects' })).toBeTruthy()
  })

  it('shows one vague message for wrong credentials and stays on the form', async () => {
    const api = signedOutApi({ login: () => Promise.reject(new ApiError(401, 'invalid_credentials', 'Invalid email or password')) })
    renderApp(api, '/signin')
    await screen.findByRole('heading', { name: 'Sign in' })
    signIn()
    expect((await screen.findByRole('alert')).textContent).toMatch(/email or password is incorrect/)
    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeTruthy()
  })

  it('validates empty fields before calling the server', async () => {
    const api = signedOutApi({ login: vi.fn() })
    renderApp(api, '/signin')
    await screen.findByRole('heading', { name: 'Sign in' })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Enter your email address.')).toBeTruthy()
    expect(api.login).not.toHaveBeenCalled()
  })

  it('signs out and returns to the public pages', async () => {
    const api = fakeApi({ logout: vi.fn().mockResolvedValue() })
    renderApp(api, '/account')
    expect(await screen.findByRole('heading', { level: 1, name: 'Account' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    await waitFor(() => expect(api.logout).toHaveBeenCalled())
    expect((await screen.findAllByRole('link', { name: 'Sign in' })).length).toBeGreaterThan(0)
  })
})

describe('session expiry (real API client, stubbed network)', () => {
  beforeEach(() => vi.stubGlobal('fetch', vi.fn()))
  afterEach(() => vi.unstubAllGlobals())

  it('a 401 from a protected call returns the user to sign-in with a clear message', async () => {
    const respond = (status, body) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
    fetch.mockImplementation((url) => {
      if (url.endsWith('/auth/me')) return respond(200, { user, csrf_token: 'tok' })
      return respond(401, { error: { code: 'unauthenticated', message: 'Sign in required' } })
    })
    render(
      <MemoryRouter initialEntries={['/projects']}>
        <App api={realApi} />
      </MemoryRouter>,
    )
    expect(await screen.findByText('Your session ended')).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeTruthy()
  })
})
