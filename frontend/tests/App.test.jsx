import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import App from '../src/app/App.jsx'

const signedOut = { me: () => Promise.reject(new Error('no session')) }

describe('App', () => {
  it('renders the heading and the sign-in form when there is no session', async () => {
    render(<App api={signedOut} />)
    expect(screen.getByRole('heading', { name: 'Sentinel AI' })).toBeTruthy()
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeTruthy()
  })
})
