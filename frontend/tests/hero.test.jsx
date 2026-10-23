import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import HeroVisual from '../src/features/home/HeroVisual.jsx'

const motionCount = (container) => container.querySelectorAll('animateMotion').length
const prefersReducedMotion = (reduce) => {
  window.matchMedia = () => ({ matches: reduce, addEventListener() {}, removeEventListener() {} })
}

describe('hero animation', () => {
  it('moves the arrows by default, is hidden from assistive technology, and can be paused', () => {
    prefersReducedMotion(false)
    const { container } = render(<HeroVisual />)
    expect(motionCount(container)).toBeGreaterThan(0)
    expect(container.querySelector('.hv').getAttribute('aria-hidden')).toBe('true')
    fireEvent.click(screen.getByRole('button', { name: 'Pause animation' }))
    expect(motionCount(container)).toBe(0) // arrows rest in place
    expect(container.querySelector('.hv').className).toMatch(/hv-static/)
    fireEvent.click(screen.getByRole('button', { name: 'Play animation' }))
    expect(motionCount(container)).toBeGreaterThan(0)
  })

  it('does not animate at all when the system asks for reduced motion', () => {
    prefersReducedMotion(true)
    const { container } = render(<HeroVisual />)
    expect(motionCount(container)).toBe(0)
    expect(container.querySelector('.hv').className).toMatch(/hv-static/)
    expect(screen.getByRole('button', { name: /reduced motion/ }).disabled).toBe(true)
  })
})
