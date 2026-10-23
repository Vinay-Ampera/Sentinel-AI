import { fireEvent, screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderApp, signedOutApi } from './helpers.jsx'

function mockSystemDark(initial) {
  let listener = null
  const query = {
    matches: initial,
    addEventListener: (_e, fn) => { listener = fn },
    removeEventListener: () => { listener = null },
  }
  window.matchMedia = () => query
  return (next) => {
    query.matches = next
    if (listener) listener({ matches: next })
  }
}

describe('app shell', () => {
  it('has a skip link, primary navigation and main landmark, and no sidebar', async () => {
    renderApp(signedOutApi())
    await screen.findByRole('heading', { level: 1 })
    expect(screen.getByRole('link', { name: 'Skip to main content' }).getAttribute('href')).toBe('#main')
    expect(screen.getByRole('navigation', { name: 'Primary' })).toBeTruthy()
    expect(screen.getByRole('main')).toBeTruthy()
    expect(screen.queryByRole('complementary')).toBeNull()
  })

  it('collapses the menu behind a labelled button; Escape closes it and restores focus', async () => {
    renderApp(signedOutApi())
    await screen.findByRole('heading', { level: 1 })
    fireEvent.click(screen.getByRole('button', { name: 'Open menu' }))
    const open = screen.getByRole('button', { name: 'Close menu' })
    expect(open.getAttribute('aria-expanded')).toBe('true')
    fireEvent.keyDown(open, { key: 'Escape' })
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Open menu' }))
  })

  it('shows a not-found page with a way back, and moves focus to main on navigation', async () => {
    renderApp(signedOutApi(), '/no/such/page')
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeTruthy()
    fireEvent.click(screen.getByRole('link', { name: 'Go to the home page' }))
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('main')))
  })
})

describe('theme switching', () => {
  it('applies Light, Dark and System, persists the explicit choice, and follows the OS in System', async () => {
    const setSystemDark = mockSystemDark(false)
    renderApp(signedOutApi())
    await screen.findByRole('heading', { level: 1 })
    const root = document.documentElement
    expect(root.dataset.theme).toBe('light')

    fireEvent.click(screen.getByRole('button', { name: 'Dark' }))
    expect(root.dataset.theme).toBe('dark')
    expect(window.localStorage.getItem('sentinel-theme')).toBe('dark')
    expect(screen.getByRole('button', { name: 'Dark' }).getAttribute('aria-pressed')).toBe('true')

    fireEvent.click(screen.getByRole('button', { name: 'System' }))
    expect(window.localStorage.getItem('sentinel-theme')).toBeNull()
    setSystemDark(true)
    await waitFor(() => expect(root.dataset.theme).toBe('dark'))
  })

  it('restores the saved choice on load', async () => {
    mockSystemDark(false)
    window.localStorage.setItem('sentinel-theme', 'dark')
    renderApp(signedOutApi())
    await screen.findByRole('heading', { level: 1 })
    expect(document.documentElement.dataset.theme).toBe('dark')
  })
})
