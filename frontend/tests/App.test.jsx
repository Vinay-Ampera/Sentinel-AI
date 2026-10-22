import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import App from '../src/app/App.jsx'

describe('App', () => {
  it('renders the heading', () => {
    render(<App />)
    expect(screen.getByRole('heading', { name: 'Sentinel AI' })).toBeTruthy()
  })
})
