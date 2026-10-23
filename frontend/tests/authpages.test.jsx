import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderApp, signedOutApi } from './helpers.jsx'

describe('sign-in and request-access pages', () => {
  it.each(['/signin', '/request-access'])('%s has a minimal top bar, no footer and a decorative backdrop', async (path) => {
    const { container } = renderApp(signedOutApi(), path)
    await screen.findByRole('heading', { level: 1 })
    expect(screen.queryByRole('contentinfo')).toBeNull() // no footer
    expect(screen.queryByRole('navigation', { name: 'Primary' })).toBeNull() // brand and theme only
    expect(screen.getByRole('button', { name: 'Dark' })).toBeTruthy() // theme control is still there
    expect(container.querySelector('.auth-backdrop').getAttribute('aria-hidden')).toBe('true')
  })

  it('keeps the footer and full navigation on the other public pages', async () => {
    renderApp(signedOutApi(), '/roadmap')
    await screen.findByRole('heading', { level: 1, name: 'Roadmap' })
    expect(screen.getByRole('contentinfo')).toBeTruthy()
    expect(screen.getByRole('navigation', { name: 'Primary' })).toBeTruthy()
  })

  it('marks the current tab, and offers request access instead of a sign-up form', async () => {
    renderApp(signedOutApi(), '/signin?next=%2Fapprovals')
    await screen.findByRole('heading', { name: 'Sign in' })
    const tabs = screen.getByRole('navigation', { name: 'Account' })
    expect(within(tabs).getByRole('link', { name: 'Sign in' }).getAttribute('aria-current')).toBe('page')
    expect(within(tabs).getByRole('link', { name: 'Sign in' }).getAttribute('href')).toBe('/signin?next=%2Fapprovals') // keeps where you were going
    expect(within(tabs).getByRole('link', { name: 'Request access' }).getAttribute('aria-current')).toBeNull()
    expect(screen.queryByRole('button', { name: /sign up|register/i })).toBeNull()
  })

  it('sends /signup to the request-access page, which says it sends nothing', async () => {
    renderApp(signedOutApi(), '/signup')
    expect(await screen.findByRole('heading', { level: 1, name: 'Request access' })).toBeTruthy()
    expect(screen.getByText('This page does not send a request')).toBeTruthy()
    expect(screen.queryByRole('textbox')).toBeNull() // no form fields
  })
})
