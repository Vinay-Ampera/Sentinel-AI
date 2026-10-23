import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { fakeApi, renderApp, signedOutApi, user } from './helpers.jsx'

describe('navbar account control', () => {
  it('is one icon link to the account page, with no name text and no Sign out button', async () => {
    renderApp(fakeApi(), '/projects')
    await screen.findByRole('heading', { level: 1, name: 'Projects' })
    const nav = document.querySelector('header.navbar')
    const account = within(nav).getByRole('link', { name: 'Account: Dana Dev (developer)' })
    expect(account.getAttribute('href')).toBe('/account')
    expect(within(nav).queryByRole('button', { name: 'Sign out' })).toBeNull()
  })

  it('moves Sign out to the account page, which returns to the public home page', async () => {
    renderApp(fakeApi(), '/account')
    fireEvent.click(await screen.findByRole('button', { name: 'Sign out' }))
    await waitFor(() => expect(screen.getAllByRole('link', { name: 'Sign in' }).length).toBeGreaterThan(0))
    expect(screen.getByRole('heading', { level: 1 }).textContent).toMatch(/trace back to evidence/)
  })
})

describe('footer follows the sign-in state', () => {
  it('gives visitors an introduction with the tagline and ways in', async () => {
    renderApp(signedOutApi(), '/roadmap')
    const footer = await screen.findByRole('contentinfo')
    expect(within(footer).getByText('Test results you can trace back to evidence.')).toBeTruthy()
    expect(within(footer).getByRole('link', { name: 'Request access' })).toBeTruthy()
    expect(within(footer).getByRole('link', { name: 'Sign in' })).toBeTruthy()
    expect(within(footer).queryByRole('link', { name: 'Projects' })).toBeNull()
    expect(within(footer).getByText('Accounts are created by an administrator.')).toBeTruthy()
  })

  it('gives signed-in users working links and who they are signed in as', async () => {
    renderApp(fakeApi(), '/roadmap')
    const footer = await screen.findByRole('contentinfo')
    await within(footer).findByRole('link', { name: 'Projects' })
    expect(within(footer).getByRole('link', { name: 'Account and sessions' })).toBeTruthy()
    expect(within(footer).queryByRole('link', { name: 'Request access' })).toBeNull()
    expect(within(footer).getByText(`Signed in as ${user.display_name} (developer)`)).toBeTruthy()
  })
})

describe('brand logo', () => {
  it('sits beside the product name in the navbar and the footer, as decoration only', async () => {
    const { container } = renderApp(signedOutApi(), '/roadmap')
    await screen.findByRole('contentinfo')
    const brand = within(document.querySelector('header.navbar')).getByRole('link', { name: 'Sentinel AI' })
    expect(brand.querySelectorAll('img').length).toBe(2) // light and dark renderings; CSS shows one
    expect([...brand.querySelectorAll('img')].every((img) => img.getAttribute('alt') === '')).toBe(true)
    expect(within(screen.getByRole('contentinfo')).getByText('Sentinel AI').querySelector('.brand-logo')).toBeTruthy()
    expect(container.querySelector('.brand-logo').getAttribute('aria-hidden')).toBe('true')
  })

  it('keeps the logo on the quiet sign-in bar too', async () => {
    renderApp(signedOutApi(), '/signin')
    await screen.findByRole('heading', { level: 1 })
    expect(within(document.querySelector('header.navbar')).getByRole('link', { name: 'Sentinel AI' }).querySelector('img')).toBeTruthy()
  })
})
